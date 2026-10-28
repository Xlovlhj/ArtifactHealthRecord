import os
import tempfile
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ["AHR_RUNTIME_DIR"]=tempfile.mkdtemp(prefix="ahr-tests-")
os.environ["AHR_DEMO_MODE"]="true"
os.environ["AHR_ENV"]="development"
os.environ["AHR_DATABASE_URL"]=""
os.environ["AHR_LLM_API_KEY"]=""
os.environ["AHR_STORAGE"]="local"
os.environ["AHR_BOOTSTRAP_PASSWORD"]="ahr-demo-2026"
os.environ["AHR_REDIS_URL"]=""
os.environ["AHR_ALLOW_EXTERNAL_MODELS"]="false"
os.environ["AHR_SEGMENTATION_CHECKPOINT"]=""
os.environ["AHR_INPAINT_METHOD"]="interpolation"
os.environ["AHR_INPAINT_CHECKPOINT"]=""


os.environ["AHR_SAM_MODEL_DIR"]=""
os.environ["AHR_RETRIEVAL_MODEL_DIR"]=""
