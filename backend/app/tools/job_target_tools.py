class ToolScopeViolation(ValueError):
    pass


class ScopedJobTargetReader:
    def __init__(self, *, target_id: str, allowed_project_ids: frozenset[str], get_target, get_project) -> None:
        self.target_id = target_id
        self.allowed_project_ids = allowed_project_ids
        self._get_target = get_target
        self._get_project = get_project

    def read_target(self, target_id: str):
        if target_id != self.target_id:
            raise ToolScopeViolation("target is outside the execution manifest")
        return self._get_target(target_id)

    def read_project(self, project_id: str):
        if project_id not in self.allowed_project_ids:
            raise ToolScopeViolation("project is outside the execution manifest")
        return self._get_project(project_id)
