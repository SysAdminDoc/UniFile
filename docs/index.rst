UniFile SDK
===========

The UniFile SDK exposes the desktop application's core classification,
tag-library, semantic-search, and adaptive-learning engines to Python
applications without requiring PyQt6.

The SDK is deliberately local-first: it does not download models, start
services, or install dependencies at import time. Optional ONNX and Ollama
backends are selected by the embedding host.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   api
   tutorials/custom-classifier
   tutorials/s3-integration

Installation
------------

Build the wheel from the repository with ``make sdk`` and install it into an
embedding application's environment::

   pip install dist/sdk/unifile_sdk-9.3.32-py3-none-any.whl

The public imports are::

   from unifile_sdk import Classifier, PatternLearner, SemanticIndex, TagLibrary
