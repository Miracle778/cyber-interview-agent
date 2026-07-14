from __future__ import annotations


class ReviewDomainError(RuntimeError):
    """Base class for stable review-domain failures."""


class InsufficientQuestionsError(ReviewDomainError):
    def __init__(self, *, available: int, requested: int) -> None:
        self.available = available
        self.requested = requested
        super().__init__(
            f"only {available} questions are available; {requested} requested"
        )


class InputAlreadyResolvedError(ReviewDomainError):
    pass


class ReviewRoundNotFoundError(ReviewDomainError):
    pass


class ReviewConflictError(ReviewDomainError):
    pass


class PublicationProjectionError(ReviewDomainError):
    pass

