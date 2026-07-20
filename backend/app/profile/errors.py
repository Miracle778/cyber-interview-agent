from __future__ import annotations


class ProfileDomainError(RuntimeError):
    """Base class for stable profile-domain failures.

    Each subclass exposes a stable ``code`` string used by the API error envelope
    so callers can branch on error codes without parsing messages.
    """

    code = "profile_error"


class ProfileMaterialNotFound(ProfileDomainError):
    code = "profile_material_not_found"

    def __init__(self, material_id: str, *, workspace_id: str | None = None) -> None:
        self.material_id = material_id
        self.workspace_id = workspace_id
        super().__init__(f"profile material not found: {material_id}")


class ProfileMaterialVersionNotFound(ProfileDomainError):
    code = "profile_material_version_not_found"

    def __init__(self, version_id: str) -> None:
        self.version_id = version_id
        super().__init__(f"profile material version not found: {version_id}")


class ProfileEvidenceMismatch(ProfileDomainError):
    code = "profile_evidence_mismatch"


class ProfileProposalNotFound(ProfileDomainError):
    code = "profile_proposal_not_found"

    def __init__(self, proposal_id: str) -> None:
        self.proposal_id = proposal_id
        super().__init__(f"profile proposal not found: {proposal_id}")


class ProfileProposalAlreadyDecided(ProfileDomainError):
    code = "profile_proposal_already_decided"


class ProfileClaimNotFound(ProfileDomainError):
    code = "profile_claim_not_found"

    def __init__(self, claim_id: str) -> None:
        self.claim_id = claim_id
        super().__init__(f"profile claim not found: {claim_id}")


class ProfileClaimVersionConflict(ProfileDomainError):
    code = "profile_claim_version_conflict"


class ProfileSnapshotChanged(ProfileDomainError):
    code = "profile_snapshot_changed"


class ProfileActionPlanNotFound(ProfileDomainError):
    code = "profile_action_plan_not_found"

    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id
        super().__init__(f"profile action plan not found: {plan_id}")


class ProfileActionPlanItemNotFound(ProfileDomainError):
    code = "profile_action_plan_item_not_found"

    def __init__(self, item_id: str) -> None:
        self.item_id = item_id
        super().__init__(f"profile action plan item not found: {item_id}")


class ProfilePublicationSelectionNotFound(ProfileDomainError):
    code = "profile_publication_selection_not_found"

    def __init__(self, selection_id: str) -> None:
        self.selection_id = selection_id
        super().__init__(f"profile publication selection not found: {selection_id}")


class ProfileAssessmentNotFound(ProfileDomainError):
    code = "profile_assessment_not_found"

    def __init__(self, assessment_id: str) -> None:
        self.assessment_id = assessment_id
        super().__init__(f"profile assessment not found: {assessment_id}")


# --- Upload / storage / parsing ---


class ProfileUploadTooLarge(ProfileDomainError):
    code = "profile_upload_too_large"


class ProfileUnsupportedFileType(ProfileDomainError):
    code = "profile_unsupported_file_type"


class ProfileFileNameInvalid(ProfileDomainError):
    code = "profile_filename_invalid"


class ProfileStorageError(ProfileDomainError):
    code = "profile_storage_error"


class ProfileParseError(ProfileDomainError):
    code = "profile_parse_failed"


class ProfileEncryptedDocument(ProfileParseError):
    code = "profile_encrypted_document"


class ProfileNoExtractableText(ProfileParseError):
    code = "profile_no_extractable_text"
