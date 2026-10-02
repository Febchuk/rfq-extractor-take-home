"""Raised when a model call cannot be made or fails."""


class ModelConfigError(RuntimeError):
    """An API key or model setting is missing."""


class ExtractionError(RuntimeError):
    """The generative extractor returned something we could not use."""
