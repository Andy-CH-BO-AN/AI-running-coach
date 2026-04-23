import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pipeline.runner import run_pipeline

if __name__ == '__main__':
    run_pipeline()