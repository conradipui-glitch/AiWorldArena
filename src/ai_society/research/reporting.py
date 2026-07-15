from __future__ import annotations

from html import escape

from ai_society.experiment.models import ExperimentBundle
from ai_society.research.models import (
    Chart,
    ChartPoint,
    ModelReportRow,
    ResearchReport,
    ReproducibilityManifest,
    RunComparison,
)
from ai_society.research.persistence import report_digest


def _markdown_cell(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def build_research_report(
    bundle: ExperimentBundle, manifest: ReproducibilityManifest
) -> ResearchReport:
    metrics = {item.agent_id: item for item in bundle.metrics.agents}
    model_table: list[ModelReportRow] = []
    action_points: list[ChartPoint] = []
    resource_points: list[ChartPoint] = []
    for agent_id in sorted(bundle.initial_state.agents):
        agent = bundle.initial_state.agents[agent_id]
        metric = metrics[agent_id]
        model_table.append(
            ModelReportRow(
                agent_id=agent_id,
                provider=agent.mind.provider,
                model=agent.mind.model,
                decisions=metric.decisions,
                successful_actions=metric.successful_actions,
                rejected_actions=metric.rejected_actions,
                model_requests=metric.model_requests,
                charged_tokens=metric.charged_tokens,
                latency_ms=metric.latency_ms,
            )
        )
        action_points.append(
            ChartPoint(label=agent.identity.name, value=metric.successful_actions)
        )
        resource_points.append(
            ChartPoint(
                label=agent.identity.name,
                value=sum(metric.resources_gathered.values()),
            )
        )
    draft = ResearchReport(
        artifact_name=manifest.artifact_name,
        manifest_digest=manifest.manifest_digest,
        summary={
            "run_id": bundle.final_state.run.run_id,
            "duration_minutes": bundle.metrics.duration_minutes,
            "decisions": bundle.metrics.decisions,
            "successful_actions": bundle.metrics.successful_actions,
            "rejected_actions": bundle.metrics.rejected_actions,
            "structures": bundle.metrics.structures,
            "projects_completed": bundle.metrics.projects_completed,
            "interventions": bundle.metrics.interventions,
            "exact_decision_replay_verified": manifest.exact_decision_replay_verified,
        },
        charts=[
            Chart(
                chart_id="successful-actions",
                title="Успешные действия по агентам",
                unit="действия",
                points=action_points,
            ),
            Chart(
                chart_id="gathered-resources",
                title="Собранные ресурсы по агентам",
                unit="единицы",
                points=resource_points,
            ),
        ],
        model_table=model_table,
        report_digest="0" * 64,
    )
    return draft.model_copy(update={"report_digest": report_digest(draft)})


def _bar(value: int, maximum: int) -> str:
    if maximum <= 0:
        return ""
    return "█" * max(1, round(value / maximum * 24))


def render_report_markdown(report: ResearchReport, manifest: ReproducibilityManifest) -> str:
    lines = [
        f"# Исследовательский отчёт: {_markdown_cell(report.artifact_name)}",
        "",
        "## Воспроизводимость",
        "",
        f"- Режим: `{_markdown_cell(manifest.mode.value)}`",
        f"- Маркировки: `{', '.join(mark.value for mark in manifest.marks)}`",
        f"- Мир / правила: `{_markdown_cell(manifest.engine_version)}` / `{_markdown_cell(manifest.rules_version)}`",
        f"- Точный Decision Replay: `{'подтверждён' if manifest.exact_decision_replay_verified else 'не подтверждён'}`",
        f"- State hash: `{manifest.final_state_hash}`",
        f"- Event digest: `{manifest.final_event_digest}`",
        "",
        "## Итог",
        "",
        "| Метрика | Значение |",
        "|---|---:|",
    ]
    for key, value in report.summary.items():
        lines.append(f"| {_markdown_cell(key)} | {_markdown_cell(value)} |")
    lines.extend(["", "## Ключевые графики", ""])
    for chart in report.charts:
        maximum = max(point.value for point in chart.points)
        lines.append(f"### {_markdown_cell(chart.title)}")
        lines.append("")
        for point in chart.points:
            lines.append(
                f"- {_markdown_cell(point.label)}: `{point.value}` {_bar(point.value, maximum)}"
            )
        lines.append("")
    lines.extend(
        [
            "## Сравнительная таблица моделей",
            "",
            "| Агент | Provider | Модель | Решения | Успешно | Отклонено | Запросы | Токены | Задержка, мс |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report.model_table:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    row.agent_id,
                    row.provider,
                    row.model,
                    row.decisions,
                    row.successful_actions,
                    row.rejected_actions,
                    row.model_requests,
                    row.charged_tokens,
                    row.latency_ms,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            f"Данные графиков: `{report.artifact_name}-charts.svg`.",
            "",
            "Ограничение: этот отчёт описывает записанные результаты и расхождения; он не доказывает их причинность.",
        ]
    )
    return "\n".join(lines)


def render_report_svg(report: ResearchReport) -> str:
    """Render two compact, escaped SVG bar charts without a browser dependency."""

    rows = sum(len(chart.points) + 2 for chart in report.charts)
    height = max(260, 56 + rows * 30)
    y = 34
    fragments = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="920" height="{height}" viewBox="0 0 920 {height}" role="img" aria-label="Ключевые метрики эксперимента">',
        '<rect width="100%" height="100%" fill="#101826"/>',
        '<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#e8efff}.label{font-size:14px}.title{font-size:18px;font-weight:600}.value{font-size:13px;fill:#b8c8e8}</style>',
        '<text x="28" y="24" class="title">Ключевые метрики эксперимента</text>',
    ]
    palette = ["#58a6ff", "#6ee7b7", "#c084fc"]
    for chart_index, chart in enumerate(report.charts):
        y += 32
        fragments.append(
            f'<text x="28" y="{y}" class="title">{escape(chart.title)}</text>'
        )
        maximum = max(point.value for point in chart.points) or 1
        for point in chart.points:
            y += 26
            width = round(point.value / maximum * 500)
            fragments.extend(
                [
                    f'<text x="42" y="{y}" class="label">{escape(point.label)}</text>',
                    f'<rect x="250" y="{y - 15}" width="560" height="16" rx="3" fill="#22314a"/>',
                    f'<rect x="250" y="{y - 15}" width="{width}" height="16" rx="3" fill="{palette[chart_index % len(palette)]}"/>',
                    f'<text x="824" y="{y}" class="value">{point.value} {escape(chart.unit)}</text>',
                ]
            )
        y += 10
    fragments.append("</svg>")
    return "\n".join(fragments)


def render_comparison_markdown(comparison: RunComparison) -> str:
    divergence = comparison.first_divergence
    lines = [
        f"# Сравнение запусков: {_markdown_cell(comparison.left_artifact_name)} и {_markdown_cell(comparison.right_artifact_name)}",
        "",
        f"- Сопоставимы по миру и правилам: `{'да' if comparison.comparable else 'нет'}`",
        f"- Причины несопоставимости: `{', '.join(comparison.comparability_reasons) or 'нет'}`",
        (
            "- Первая точка расхождения: `не обнаружена`"
            if divergence is None
            else "- Первая точка расхождения: "
            f"`{divergence.stream} #{divergence.ordinal}`, минута `{divergence.game_minute}`, поле `{divergence.field}`"
        ),
        "",
        "## Таблица моделей и дельт (правый − левый)",
        "",
        "| Агент | Левая модель | Правая модель | Δ решений | Δ успехов | Δ отклонений | Δ запросов | Δ токенов | Δ мс |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison.model_table:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    row.agent_id,
                    f"{row.left_provider}/{row.left_model}",
                    f"{row.right_provider}/{row.right_model}",
                    row.decision_delta,
                    row.successful_action_delta,
                    row.rejected_action_delta,
                    row.model_request_delta,
                    row.charged_token_delta,
                    row.latency_ms_delta,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Сравнение фиксирует наблюдаемую разницу, а не её причинное объяснение.",
        ]
    )
    return "\n".join(lines)
