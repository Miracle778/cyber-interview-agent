from __future__ import annotations


class RetrospectiveDomainError(RuntimeError):
    code = "retrospective_error"


class RetrospectiveNotFound(RetrospectiveDomainError):
    code = "retrospective_not_found"


class RetrospectiveTargetRequired(RetrospectiveDomainError):
    code = "retrospective_target_required"


class RetrospectiveSourceTooLarge(RetrospectiveDomainError):
    code = "retrospective_source_too_large"


class RetrospectiveSourceUnsupported(RetrospectiveDomainError):
    code = "retrospective_source_unsupported"


class RetrospectiveSourceCleared(RetrospectiveDomainError):
    code = "retrospective_source_cleared"


class RetrospectiveCleanupNotConfirmed(RetrospectiveDomainError):
    code = "retrospective_cleanup_not_confirmed"


class RetrospectiveBusy(RetrospectiveDomainError):
    code = "retrospective_busy"


class RetrospectiveVersionConflict(RetrospectiveDomainError):
    code = "retrospective_version_conflict"


class RetrospectiveIdempotencyConflict(RetrospectiveDomainError):
    code = "retrospective_idempotency_conflict"


class RetrospectiveQuestionConfirmationRequired(RetrospectiveDomainError):
    code = "retrospective_question_confirmation_required"


class RetrospectiveCandidateConflict(RetrospectiveDomainError):
    code = "retrospective_candidate_conflict"


class RetrospectiveDeleteBlocked(RetrospectiveDomainError):
    code = "retrospective_delete_blocked"


class RetrospectiveModelNotConfigured(RetrospectiveDomainError):
    code = "retrospective_model_not_configured"


class RetrospectiveAnalysisFailed(RetrospectiveDomainError):
    code = "retrospective_analysis_failed"
