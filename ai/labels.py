"""Local six-class vocabulary; this is not a replacement for a purchased standard."""

LABELS = {"背景": 0, "起甲": 1, "酥碱": 2, "空鼓": 3, "裂隙": 4, "颜料层脱落": 5, "地仗脱落": 6}
CLASS_NAMES = list(LABELS)
BINARY_CLASS_NAMES = ["背景", "病害区域（未分类）"]
IGNORE_INDEX = 255
PALETTE = [(0, 0, 0), (224, 122, 66), (218, 186, 73), (145, 111, 190),
           (218, 74, 79), (70, 154, 175), (94, 143, 93)]
