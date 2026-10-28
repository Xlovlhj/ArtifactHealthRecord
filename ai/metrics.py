"""Confusion-based metrics: absent classes are null, never artificially perfect."""
import numpy as np

from .labels import CLASS_NAMES


def confusion_matrix(target, prediction, num_classes=7):
    target, prediction = np.asarray(target).ravel(), np.asarray(prediction).ravel()
    valid = (target >= 0) & (target < num_classes)
    if not np.all((prediction[valid] >= 0) & (prediction[valid] < num_classes)):
        raise ValueError("预测类别超出范围")
    return np.bincount(num_classes * target[valid].astype(int) + prediction[valid].astype(int),
                       minlength=num_classes**2).reshape(num_classes, num_classes)


def metrics_from_confusion(matrix, class_names=None):
    matrix = np.asarray(matrix, dtype=np.int64)
    class_names = class_names or CLASS_NAMES
    if matrix.shape != (len(class_names), len(class_names)):
        raise ValueError("混淆矩阵与类别表维度不符")
    per_class = {}
    for index, label in enumerate(class_names):
        tp = int(matrix[index, index])
        actual, predicted = int(matrix[index].sum()), int(matrix[:, index].sum())
        union, total = actual + predicted - tp, actual + predicted
        per_class[label] = {"dice": 2*tp/total if total else None,
                            "iou": tp/union if union else None,
                            "precision": tp/predicted if predicted else None,
                            "recall": tp/actual if actual else None,
                            "f1": 2*tp/total if total else None,
                            "support_pixels": actual, "predicted_pixels": predicted}
    scores = [v["dice"] for key,v in per_class.items() if key != "背景" and v["dice"] is not None]
    return {"per_class": per_class, "macro_dice": float(np.mean(scores)) if scores else None,
            "evaluated_disease_classes": len(scores), "total_disease_classes": len(class_names)-1,
            "macro_definition": "当前类别表中真值或预测存在的病害类别等权平均；背景不参与；缺失类为 null",
            "confusion_matrix": matrix.tolist()}
