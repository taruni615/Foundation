"""Compatibility shim: export_qa logic has moved to edu_pipeline.export."""

from edu_pipeline.export import *
from edu_pipeline.export import _looks_like_pairing_option
from edu_pipeline.export import main

if __name__ == "__main__":
    main()
