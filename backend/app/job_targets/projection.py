from dataclasses import asdict


def resource(record):
    return asdict(record)


def retrospective_summary_resource(summary: dict[str, object]) -> dict[str, object]:
    """Keep the target overview compact and free of report/source bodies."""
    return {
        "retrospectiveCount": summary["retrospectiveCount"],
        "latest": summary["latest"],
        "unresolvedActionCount": summary["unresolvedActionCount"],
        "gapCounts": summary["gapCounts"],
        "timeline": summary["timeline"],
    }
