"""An original compact U-Net implementation plus optional upstream adapters."""
from __future__ import annotations

import torch
from pathlib import Path
from torch import nn
from torch.nn import functional as F


def _block(in_channels: int, out_channels: int):
    return nn.Sequential(nn.Conv2d(in_channels, out_channels, 3, padding=1),
                         nn.GroupNorm(4, out_channels), nn.ReLU(inplace=True),
                         nn.Conv2d(out_channels, out_channels, 3, padding=1),
                         nn.GroupNorm(4, out_channels), nn.ReLU(inplace=True))


class UNet(nn.Module):
    """Three-resolution U-Net, randomly initialized; no implied pretrained weights."""
    def __init__(self, num_classes=7, base_channels=16):
        super().__init__()
        if base_channels < 4 or base_channels % 4:
            raise ValueError("base_channels 必须是 ≥4 的 4 的倍数")
        b = base_channels
        self.enc1, self.enc2, self.enc3 = _block(3, b), _block(b, b*2), _block(b*2, b*4)
        self.bridge = _block(b*4, b*8)
        self.dec3, self.dec2, self.dec1 = _block(b*12, b*4), _block(b*6, b*2), _block(b*3, b)
        self.head = nn.Conv2d(b, num_classes, 1)

    def forward(self, x):
        a = self.enc1(x)
        b = self.enc2(F.max_pool2d(a, 2))
        c = self.enc3(F.max_pool2d(b, 2))
        z = self.bridge(F.max_pool2d(c, 2))
        for decoder, skip in ((self.dec3, c), (self.dec2, b), (self.dec1, a)):
            z = decoder(torch.cat([F.interpolate(z, size=skip.shape[-2:], mode="bilinear", align_corners=False), skip], dim=1))
        return self.head(z)


class SegFormerAdapter(nn.Module):
    def __init__(self, pretrained=None, num_classes=7):
        super().__init__()
        from transformers import SegformerConfig, SegformerForSemanticSegmentation
        from .labels import CLASS_NAMES, BINARY_CLASS_NAMES
        names = BINARY_CLASS_NAMES if num_classes == 2 else CLASS_NAMES
        if pretrained:
            self.model = SegformerForSemanticSegmentation.from_pretrained(
                pretrained, num_labels=num_classes, ignore_mismatched_sizes=True,
                id2label=dict(enumerate(names)), label2id={n:i for i,n in enumerate(names)})
        else:
            self.model = SegformerForSemanticSegmentation(SegformerConfig(num_labels=num_classes))

    def forward(self, x):
        logits = self.model(pixel_values=x).logits
        return F.interpolate(logits, size=x.shape[-2:], mode="bilinear", align_corners=False)


def build_model(architecture="unet", base_channels=16, pretrained=None, num_classes=7):
    if num_classes not in {2, 7}:
        raise ValueError("支持病害二分类或六类病害+背景")
    if architecture == "unet":
        if pretrained:
            raise ValueError("紧凑 U-Net 不提供预训练编码器；使用 unet-resnet34 或 --resume")
        return UNet(base_channels=base_channels, num_classes=num_classes)
    if architecture == "unet-resnet34":
        import segmentation_models_pytorch as smp
        local = pretrained and Path(pretrained).is_file()
        model = smp.Unet(encoder_name="resnet34", encoder_weights=None if local else pretrained, in_channels=3, classes=num_classes)
        if local:
            state = torch.load(pretrained, map_location="cpu", weights_only=True)
            # Torchvision's classifier is not part of a segmentation encoder.
            state = {name: value for name, value in state.items() if not name.startswith("fc.")}
            model.encoder.load_state_dict(state, strict=True)
        return model
    if architecture == "segformer-b0":
        return SegFormerAdapter(pretrained, num_classes)
    raise ValueError(f"未知网络: {architecture}")


class CombinedLoss(nn.Module):
    def __init__(self, ce_weight=.5, dice_weight=.5):
        super().__init__()
        self.ce_weight, self.dice_weight = ce_weight, dice_weight

    def forward(self, logits, targets):
        valid = targets != 255
        if not valid.any():
            return logits.sum() * 0
        ce = F.cross_entropy(logits, targets, ignore_index=255)
        one_hot = F.one_hot(targets.masked_fill(~valid, 0), logits.shape[1]).permute(0, 3, 1, 2).float()
        probabilities = logits.softmax(1) * valid.unsqueeze(1)
        one_hot = one_hot * valid.unsqueeze(1)
        inter = (probabilities * one_hot).sum((0, 2, 3))
        denominator = (probabilities + one_hot).sum((0, 2, 3))
        # Exclude background; absent classes still penalize false positive mass.
        dice_loss = 1 - ((2 * inter[1:] + 1e-6) / (denominator[1:] + 1e-6)).mean()
        return self.ce_weight * ce + self.dice_weight * dice_loss
