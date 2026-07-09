from langgraph.graph import END, START, StateGraph

from app.agents.review_state import ReviewState
from app.agents.tools import evaluate_answer, select_next_question

def choose_question(state: ReviewState) -> ReviewState:
    return {"current_question": select_next_question(state["questions"], state["settings"])}

def evaluate_current_answer(state: ReviewState) -> ReviewState:
    return {"evaluation": evaluate_answer(state["current_question"], state.get("user_answer", ""))}

def generate_report(state: ReviewState) -> ReviewState:
    evaluation = state["evaluation"]
    markdown = (
        "---\n"
        "type: session_report\n"
        "status: review_pending\n"
        "---\n\n"
        "# 单轮复习报告\n\n"
        f"- question: {evaluation['question_id']}\n"
        f"- score: {evaluation['score']}\n"
        f"- missing: {', '.join(evaluation['missing_key_points']) or '无'}\n"
    )
    return {"report_markdown": markdown}

def build_review_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("choose_question", choose_question)
    graph.add_node("evaluate_answer", evaluate_current_answer)
    graph.add_node("generate_report", generate_report)
    graph.add_edge(START, "choose_question")
    graph.add_edge("choose_question", "evaluate_answer")
    graph.add_edge("evaluate_answer", "generate_report")
    graph.add_edge("generate_report", END)
    return graph.compile()
