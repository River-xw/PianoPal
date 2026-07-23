"""Analyze realtime IMU posture predictions and write score reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any
import argparse
import json
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_ROOT = ROOT / "data" / "artifacts" / "posture_reports"
NORMAL_LABEL = "normal"
STANDARD_HIGH_CONFIDENCE_THRESHOLD = 0.70


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/analyze_posture_predictions.py",
        description=(
            "Analyze imu_predictions.jsonl, merge confident posture-error "
            "segments, and write JSON/Markdown scoring reports."
        ),
    )
    parser.add_argument("predictions", type=Path, help="Path to imu_predictions.jsonl.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for posture_result.json and posture_result.md.",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=None,
        help=(
            "Minimum confidence for reportable error windows. If omitted, "
            "uses 0.70 when possible, otherwise picks an adaptive threshold."
        ),
    )
    parser.add_argument(
        "--merge-gap-sec",
        type=float,
        default=0.75,
        help="Merge neighboring same-label error windows across gaps up to this many seconds.",
    )
    parser.add_argument(
        "--normal-label",
        default=NORMAL_LABEL,
        help='Label treated as correct posture. Default: "normal".',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    predictions_path = args.predictions
    rows = load_predictions(predictions_path)
    if not rows:
        raise SystemExit(f"no predictions found in {predictions_path}")

    output_dir = args.output_dir or default_output_dir(predictions_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = analyze_predictions(
        rows,
        source_uri=predictions_path,
        normal_label=args.normal_label,
        confidence_threshold=args.confidence_threshold,
        merge_gap_sec=args.merge_gap_sec,
    )

    json_output = output_dir / "posture_result.json"
    markdown_output = output_dir / "posture_result.md"
    json_output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_output.write_text(render_markdown(result), encoding="utf-8")

    summary = result["summary"]
    print(f"posture score: {summary['score']}/100")
    print(
        "predictions: "
        f"{summary['counts']['total_predictions']} total, "
        f"{summary['counts']['normal']} normal, "
        f"{summary['counts']['posture_error_events']} error events"
    )
    print(f"report threshold: {summary['confidence']['report_high_confidence_threshold']}")
    print(f"json: {json_output}")
    print(f"markdown: {markdown_output}")
    return 0


def load_predictions(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
            if "predicted_label" not in row or "confidence" not in row:
                raise ValueError(
                    f"prediction at {path}:{line_number} must contain predicted_label and confidence"
                )
            rows.append(row)
    rows.sort(key=lambda row: (row.get("window_start_device_ms", 0), row.get("window_end_device_ms", 0)))
    return rows


def analyze_predictions(
    rows: list[dict[str, Any]],
    *,
    source_uri: Path,
    normal_label: str,
    confidence_threshold: float | None,
    merge_gap_sec: float,
) -> dict[str, Any]:
    threshold, threshold_method = choose_confidence_threshold(
        rows,
        normal_label=normal_label,
        requested_threshold=confidence_threshold,
    )

    all_counts = Counter(str(row["predicted_label"]) for row in rows)
    confidence_sums: dict[str, float] = defaultdict(float)
    for row in rows:
        confidence_sums[str(row["predicted_label"])] += float(row["confidence"])

    total_predictions = len(rows)
    normal_predictions = all_counts.get(normal_label, 0)
    total_confidence = sum(float(row["confidence"]) for row in rows)
    normal_confidence = confidence_sums.get(normal_label, 0.0)
    normal_ratio = normal_predictions / total_predictions if total_predictions else 1.0
    weighted_normal_ratio = normal_confidence / total_confidence if total_confidence else 1.0
    score = round(weighted_normal_ratio * 100.0, 2)

    high_rows = [row for row in rows if float(row["confidence"]) >= threshold]
    high_counts = Counter(str(row["predicted_label"]) for row in high_rows)
    high_normal_count = high_counts.get(normal_label, 0)
    high_normal_ratio = high_normal_count / len(high_rows) if high_rows else None
    error_events = merge_error_events(
        high_rows,
        normal_label=normal_label,
        merge_gap_sec=merge_gap_sec,
    )

    error_counts_by_label = Counter(event["posture_label"] for event in error_events)
    error_windows_by_label = Counter(
        str(row["predicted_label"])
        for row in high_rows
        if str(row["predicted_label"]) != normal_label
    )
    mean_confidence_by_error_label = {}
    for label in sorted(error_windows_by_label):
        values = [
            float(row["confidence"])
            for row in high_rows
            if str(row["predicted_label"]) == label
        ]
        mean_confidence_by_error_label[label] = round(mean(values), 4)

    confidences = [float(row["confidence"]) for row in rows]
    result = {
        "song_name": None,
        "schema_version": "posture_scoring_result_v1",
        "source_uri": str(source_uri),
        "summary": {
            "score": score,
            "sub_scores": {
                "posture": score,
                "normal_ratio": round(normal_ratio * 100.0, 2),
                "confidence_weighted_normal_ratio": score,
                "high_confidence_normal_ratio": (
                    round(high_normal_ratio * 100.0, 2)
                    if high_normal_ratio is not None
                    else None
                ),
            },
            "counts": {
                "total_predictions": total_predictions,
                "normal": normal_predictions,
                "posture_error_predictions": total_predictions - normal_predictions,
                "high_confidence_predictions": len(high_rows),
                "high_confidence_errors": sum(error_windows_by_label.values()),
                "posture_error_events": len(error_events),
            },
            "prediction_counts_by_label": dict(sorted(all_counts.items())),
            "high_confidence_counts_by_label": dict(sorted(high_counts.items())),
            "error_event_counts_by_label": dict(sorted(error_counts_by_label.items())),
            "error_window_counts_by_label": dict(sorted(error_windows_by_label.items())),
            "mean_confidence_by_error_label": mean_confidence_by_error_label,
            "confidence": {
                "min": round(min(confidences), 4),
                "max": round(max(confidences), 4),
                "mean": round(mean(confidences), 4),
                "report_high_confidence_threshold": threshold,
                "threshold_method": threshold_method,
                "standard_high_confidence_threshold": STANDARD_HIGH_CONFIDENCE_THRESHOLD,
                "standard_high_confidence_prediction_count": sum(
                    1 for row in rows if float(row["confidence"]) >= STANDARD_HIGH_CONFIDENCE_THRESHOLD
                ),
            },
            "time_range_sec": {
                "start": round(float(rows[0].get("window_start_device_ms", 0)) / 1000.0, 3),
                "end": round(float(rows[-1].get("window_end_device_ms", 0)) / 1000.0, 3),
            },
        },
        "posture_errors": error_events,
        "notes": [
            scoring_note_from_event(event)
            for event in error_events
        ],
        "method": {
            "hand": "L",
            "normal_label": normal_label,
            "normal_score_formula": (
                "100 * sum(confidence for normal predictions) / "
                "sum(confidence for all predictions)"
            ),
            "error_event_rule": (
                "merge consecutive high-confidence non-normal windows with the same label "
                f"when gaps are <= {merge_gap_sec:g} sec"
            ),
            "right_hand_ignored": True,
        },
    }
    return result


def choose_confidence_threshold(
    rows: list[dict[str, Any]],
    *,
    normal_label: str,
    requested_threshold: float | None,
) -> tuple[float, str]:
    if requested_threshold is not None:
        return round(float(requested_threshold), 4), "manual"

    standard_error_count = sum(
        1
        for row in rows
        if str(row["predicted_label"]) != normal_label
        and float(row["confidence"]) >= STANDARD_HIGH_CONFIDENCE_THRESHOLD
    )
    if standard_error_count > 0:
        return STANDARD_HIGH_CONFIDENCE_THRESHOLD, "standard"

    error_confidences = sorted(
        float(row["confidence"])
        for row in rows
        if str(row["predicted_label"]) != normal_label
    )
    if not error_confidences:
        return STANDARD_HIGH_CONFIDENCE_THRESHOLD, "standard_no_errors"

    # Use the top-confidence tail when the model is uncertain overall. The
    # lower bound keeps tiny fluctuations from being reported as confident.
    percentile_index = max(0, int(len(error_confidences) * 0.85) - 1)
    adaptive = max(0.45, error_confidences[percentile_index])
    adaptive = min(STANDARD_HIGH_CONFIDENCE_THRESHOLD, adaptive)
    return round(adaptive, 4), "adaptive_85th_percentile_error_confidence"


def merge_error_events(
    rows: list[dict[str, Any]],
    *,
    normal_label: str,
    merge_gap_sec: float,
) -> list[dict[str, Any]]:
    events = []
    current = None
    merge_gap_ms = int(merge_gap_sec * 1000)

    for row in rows:
        label = str(row["predicted_label"])
        if label == normal_label:
            if current is not None:
                events.append(finalize_event(current, len(events)))
                current = None
            continue

        start_ms = int(row.get("window_start_device_ms", 0))
        end_ms = int(row.get("window_end_device_ms", start_ms))
        confidence = float(row["confidence"])
        sequence_number = int(row.get("sequence_number", 0))

        if (
            current is not None
            and current["label"] == label
            and start_ms <= current["end_device_ms"] + merge_gap_ms
        ):
            current["end_device_ms"] = max(current["end_device_ms"], end_ms)
            current["window_count"] += 1
            current["confidences"].append(confidence)
            current["sequence_numbers"].append(sequence_number)
        else:
            if current is not None:
                events.append(finalize_event(current, len(events)))
            current = {
                "label": label,
                "start_device_ms": start_ms,
                "end_device_ms": end_ms,
                "window_count": 1,
                "confidences": [confidence],
                "sequence_numbers": [sequence_number],
            }

    if current is not None:
        events.append(finalize_event(current, len(events)))
    return events


def finalize_event(event: dict[str, Any], event_index: int) -> dict[str, Any]:
    confidences = event["confidences"]
    sequence_numbers = event["sequence_numbers"]
    return {
        "event_index": event_index,
        "status": "posture_error",
        "posture_label": event["label"],
        "start_sec": round(event["start_device_ms"] / 1000.0, 3),
        "end_sec": round(event["end_device_ms"] / 1000.0, 3),
        "duration_sec": round((event["end_device_ms"] - event["start_device_ms"]) / 1000.0, 3),
        "window_count": event["window_count"],
        "mean_confidence": round(mean(confidences), 4),
        "max_confidence": round(max(confidences), 4),
        "start_sequence_number": min(sequence_numbers),
        "end_sequence_number": max(sequence_numbers),
    }


def scoring_note_from_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "ref_index": None,
        "perf_index": event["event_index"],
        "pitch_ref": None,
        "pitch_perf": None,
        "name": event["posture_label"],
        "onset_ref_sec": None,
        "onset_perf_sec": event["start_sec"],
        "offset_ms": None,
        "status": event["status"],
        "timing": None,
        "measure": None,
        "hand": "L",
        "dur_beats": None,
        "end_sec": event["end_sec"],
        "duration_sec": event["duration_sec"],
        "confidence": event["mean_confidence"],
        "max_confidence": event["max_confidence"],
        "posture_label": event["posture_label"],
        "window_count": event["window_count"],
    }


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# PianoPal Posture Scoring Result",
        "",
        f"- Source: `{Path(result['source_uri']).name}`",
        f"- Hand: {result['method']['hand']}",
        (
            f"- Time range: {summary['time_range_sec']['start']}s - "
            f"{summary['time_range_sec']['end']}s"
        ),
        f"- Posture score: **{summary['score']}/100**",
        f"- Normal ratio: {summary['sub_scores']['normal_ratio']}%",
        (
            "- Confidence-weighted normal ratio: "
            f"{summary['sub_scores']['confidence_weighted_normal_ratio']}%"
        ),
        (
            "- Report confidence threshold: "
            f">= {summary['confidence']['report_high_confidence_threshold']} "
            f"({summary['confidence']['threshold_method']})"
        ),
        (
            "- Standard threshold prediction count: "
            f"{summary['confidence']['standard_high_confidence_prediction_count']} "
            f"at >= {summary['confidence']['standard_high_confidence_threshold']}"
        ),
        "",
        "## Summary",
        "",
    ]

    for key, value in summary["counts"].items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Label Distribution", ""])
    for label, count in summary["prediction_counts_by_label"].items():
        lines.append(f"- {label}: {count}")

    lines.extend(["", "## High-Confidence Errors", ""])
    if result["posture_errors"]:
        lines.append(
            "| Error Label | Windows | Start | End | Duration | Mean Confidence | Max Confidence |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for event in result["posture_errors"]:
            lines.append(
                f"| {event['posture_label']} | {event['window_count']} | "
                f"{event['start_sec']}s | {event['end_sec']}s | "
                f"{event['duration_sec']}s | {event['mean_confidence']} | "
                f"{event['max_confidence']} |"
            )
    else:
        lines.append("No non-normal prediction reached the report threshold.")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            interpretation_text(result),
        ]
    )
    return "\n".join(lines) + "\n"


def interpretation_text(result: dict[str, Any]) -> str:
    summary = result["summary"]
    threshold_method = summary["confidence"]["threshold_method"]
    error_counts = summary["error_event_counts_by_label"]
    if not error_counts:
        return "The model did not find reportable high-confidence posture errors in this run."

    top_error = max(error_counts, key=error_counts.get)
    text = (
        f"The most prominent posture issue is `{top_error}`. "
        f"The posture score is based on the share of confidence assigned to `{NORMAL_LABEL}`."
    )
    if threshold_method.startswith("adaptive"):
        text += (
            " The model was not very confident overall, so this report used an adaptive "
            "threshold and should be read as a trend diagnosis rather than a strict final judgment."
        )
    return text


def default_output_dir(predictions_path: Path) -> Path:
    if predictions_path.name == "imu_predictions.jsonl" and predictions_path.parent.name:
        report_name = predictions_path.parent.name
    else:
        report_name = sanitize_name(predictions_path.stem)
    return DEFAULT_REPORT_ROOT / report_name


def sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return sanitized or "posture_report"


if __name__ == "__main__":
    raise SystemExit(main())
