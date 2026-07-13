class ToolError(RuntimeError):
    code = "tool_error"


class ToolNotAllowedError(ToolError):
    code = "tool_not_allowed"


class ToolScopeDeniedError(ToolError):
    code = "tool_scope_denied"


class ToolInputInvalidError(ToolError):
    code = "tool_input_invalid"


class ToolOutputInvalidError(ToolError):
    code = "tool_output_invalid"
