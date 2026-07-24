class JobTargetDomainError(RuntimeError):
    pass


class JobTargetNotFound(JobTargetDomainError):
    pass


class JobTargetConflict(JobTargetDomainError):
    pass


class JobTargetBusy(JobTargetDomainError):
    pass


class JobDocumentVersionNotFound(JobTargetDomainError):
    pass


class JobRequirementNotFound(JobTargetDomainError):
    pass


class ProjectDeepDiveNotFound(JobTargetDomainError):
    pass

