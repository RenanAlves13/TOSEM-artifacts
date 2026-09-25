"""Streamlit dashboard for exploring and running the architecture workbench.

Run from the repository root with:

    python -m streamlit run src/ui/app.py

The dashboard is intentionally local. It never renders API-key values and only
starts generation when the user explicitly confirms the action in the browser.
"""

from __future__ import annotations

from html import escape
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    import streamlit as st
except ModuleNotFoundError as exc:  # pragma: no cover - shown only before installation
    raise SystemExit(
        "The graphical interface needs Streamlit and pandas. "
        "Run: python -m pip install -r requirements.txt"
    ) from exc

from src.agentic.prompts import (
    ARCHITECT_SYSTEM_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    DOMAIN_SYSTEM_PROMPT,
    REFINER_SYSTEM_PROMPT,
    STRUCTURAL_SYSTEM_PROMPT,
    build_domain_prompt,
    build_structural_prompt,
)
from src.comparison.architecture_metrics import analyze_architecture_csv
from src.comparison.evaluate import run_comparison
from src.comparison.trace_metrics import analyze_trace
from src.prompt_builder import (
    FEW_SHOT_EXAMPLES,
    JSON_SCHEMA_SNIPPET,
    build_evidence_context,
    build_prompt,
)
from src.prompt_writer import render_prompt_text
from src.static_analysis_loader import static_analysis_totals
from src.ui.data import (
    MAX_DOWNLOAD_BYTES,
    TRACE_PREVIEW_MAX_BYTES,
    TRACE_PREVIEW_MAX_EVENTS,
    CommandResult,
    ProjectSnapshot,
    WorkspacePaths,
    build_generation_command,
    build_static_analysis_command,
    comparison_report_paths,
    default_paths,
    discover_dashboard_projects,
    exclusive_job_lock,
    format_command,
    ground_truth_files,
    load_dashboard_config,
    load_project_snapshot,
    numeric_value,
    provider_rows,
    read_comparison_manifest,
    read_csv_rows,
    read_download_bytes,
    read_jsonl_events,
    read_limited_text,
    resolve_managed_path,
    run_local_command,
    run_records,
    static_project_overview,
    validate_output_artifacts,
    write_comparison_manifest,
)


MENU_OPTIONS = [
    "Visão geral",
    "Projetos e análise estática",
    "Prompts diretos",
    "Fluxo do agente",
    "Executar experimentos",
    "Resultados gerados",
    "Comparação",
    "Configuração e documentação",
]

SENSITIVE_TRACE_FIELDS = {
    "system_prompt",
    "user_prompt",
    "raw_response",
    "parsed_output",
}


def active_outputs_value() -> str:
    """Return the last output location selected in the dashboard, if any."""
    return str(st.session_state.get("active_outputs_dir", "outputs"))


def relative_workspace_path(paths: WorkspacePaths, path: Path) -> str:
    """Display a repository-local path without leaking a machine-specific root."""
    try:
        return path.resolve().relative_to(paths.root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def render_file_download(
    path: Path,
    *,
    label: str,
    mime: str,
    key: str,
    sensitive: bool = False,
) -> None:
    """Offer a bounded download and require explicit consent for raw traces/prompts."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        st.warning(f"Não foi possível preparar o download: {exc}")
        return
    st.caption(f"Tamanho do arquivo: {size:,} bytes.")
    if size > MAX_DOWNLOAD_BYTES:
        st.warning(
            f"O arquivo excede o limite de download da interface ({MAX_DOWNLOAD_BYTES:,} bytes). "
            "Use o arquivo local diretamente."
        )
        return
    if sensitive and not st.checkbox(
        "Entendo que o download pode conter prompts e respostas brutas.",
        key=f"confirm_download_{key}",
    ):
        st.caption("Confirme acima para habilitar o download do conteúdo bruto.")
        return
    try:
        content = read_download_bytes(path)
    except ValueError as exc:
        st.warning(str(exc))
        return
    st.download_button(
        label,
        data=content,
        file_name=path.name,
        mime=mime,
        key=f"download_{key}",
    )


def main() -> None:
    st.set_page_config(
        page_title="Architecture Generation Workbench",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_style()

    paths = default_paths(ROOT)
    try:
        config = load_dashboard_config(paths)
        projects = discover_dashboard_projects(paths, config)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Não foi possível carregar a configuração do repositório: {exc}")
        st.stop()

    with st.sidebar:
        st.markdown("## 🧭 Workbench")
        st.caption("Interface local para análise, geração e comparação de arquiteturas.")
        page = st.pills(
            "Navegação",
            MENU_OPTIONS,
            selection_mode="single",
            default=MENU_OPTIONS[0],
            key="main_menu",
            width="stretch",
        )
        st.divider()
        st.caption(f"Workspace: `{paths.root.name}`")
        st.caption(f"Projetos encontrados: {len(projects)}")
        if st.button("↻ Atualizar dados", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.caption("As chaves de API nunca são exibidas pela interface.")

    if page == "Visão geral":
        render_overview(paths, config, projects)
    elif page == "Projetos e análise estática":
        render_static_analysis(paths, config, projects)
    elif page == "Prompts diretos":
        render_direct_prompts(paths, config, projects)
    elif page == "Fluxo do agente":
        render_agent_flow(paths, config, projects)
    elif page == "Executar experimentos":
        render_execution(paths, config, projects)
    elif page == "Resultados gerados":
        render_generated_results(paths, config, projects)
    elif page == "Comparação":
        render_comparison(paths, config, projects)
    else:
        render_documentation(paths, config)


def inject_style() -> None:
    """Apply a compact visual language without relying on external assets."""
    st.markdown(
        """
        <style>
          :root {
            --ink: #172033;
            --muted: #65758b;
            --surface: #ffffff;
            --soft: #f4f7fb;
            --accent: #2558d9;
            --teal: #0f9b8e;
            --warning: #b66a00;
          }
          .stApp { background: #f6f8fc; color: var(--ink); }
          [data-testid="stSidebar"] { background: #101a2c; }
          [data-testid="stSidebar"] * { color: #edf3ff; }
          [data-testid="stSidebar"] .stButton button {
            border-color: #4f6da7; background: #1d2c48;
          }
          [data-testid="stDownloadButton"] button {
            background: #2558d9; border-color: #2558d9;
          }
          [data-testid="stDownloadButton"] button,
          [data-testid="stDownloadButton"] button * {
            color: #ffffff !important;
          }
          [data-testid="stDownloadButton"] button:hover {
            background: #1d46ad; border-color: #1d46ad;
          }
          [data-testid="stBaseButton-primary"] {
            background: #2558d9; border-color: #2558d9;
          }
          [data-testid="stBaseButton-primary"]:hover {
            background: #1d46ad; border-color: #1d46ad;
          }
          details[data-testid="stExpander"][open] > summary,
          [data-testid="stExpander"] details[open] > summary {
            background: #2558d9; border-radius: 8px;
          }
          details[data-testid="stExpander"][open] > summary,
          details[data-testid="stExpander"][open] > summary *,
          [data-testid="stExpander"] details[open] > summary,
          [data-testid="stExpander"] details[open] > summary * {
            color: #ffffff !important;
          }
          [data-testid="stTabs"] [data-testid="stTab"]:not([data-selected]),
          [data-testid="stTabs"] [data-testid="stTab"]:not([data-selected]) * {
            color: #2558d9 !important;
          }
          .hero {
            background: linear-gradient(120deg, #162a52 0%, #2558d9 58%, #0f9b8e 120%);
            padding: 1.55rem 1.8rem; border-radius: 18px; color: white;
            margin: 0 0 1.35rem 0; box-shadow: 0 14px 30px rgba(23, 44, 88, .18);
          }
          .hero h1 { color: white; font-size: 2rem; margin: 0 0 .28rem 0; }
          .hero p { color: #e6eeff; margin: 0; font-size: 1rem; }
          .section-note {
            background: #eaf0ff; border-left: 4px solid #2558d9; padding: .75rem 1rem;
            border-radius: 8px; color: #253a65; margin: .65rem 0 1rem 0;
          }
          .flow-step {
            background: white; border: 1px solid #dce5f5; border-radius: 12px;
            padding: .8rem; min-height: 106px; box-shadow: 0 4px 11px rgba(35, 58, 105, .06);
          }
          .flow-step strong { color: #1d3d85; }
          .metric-label { color: #60708a; font-size: .83rem; }
          .table-filter-label {
            color: #2558d9; font-weight: 600; margin: 0 0 .2rem 0;
          }
          .package-chart-label {
            color: #000000; font-weight: 600; margin: 0 0 .2rem 0;
          }
          .direct-prompt-label {
            color: #2558d9; font-weight: 600; margin: 0 0 .2rem 0;
          }
          .direct-prompt-metric { padding: .1rem 0; }
          .direct-prompt-metric__label {
            color: #2558d9; font-size: .88rem; font-weight: 600;
          }
          .direct-prompt-metric__value {
            color: #2558d9; font-size: 1.65rem; font-weight: 700; line-height: 1.25;
          }
          .static-build-metric { padding: .1rem 0; }
          .static-build-metric__label {
            color: #2558d9; font-size: .9rem; font-weight: 600;
          }
          .static-build-metric__value {
            color: #2558d9; font-size: 2.25rem; font-weight: 700; line-height: 1.2;
          }
          .st-key-static_project_totals,
          .st-key-static_project_totals * {
            color: #000000 !important;
          }
          .st-key-static_project_totals .static-total-group-heading,
          .st-key-static_project_totals .static-total-group-heading * {
            color: #2558d9 !important;
          }
          .static-total-group-heading {
            font-weight: 700;
            margin: .85rem 0 .4rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def dataframe_from(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def filter_frame(frame: pd.DataFrame, term: str) -> pd.DataFrame:
    if frame.empty or not term.strip():
        return frame
    needle = term.casefold().strip()
    mask = frame.fillna("").astype(str).apply(
        lambda column: column.str.casefold().str.contains(needle, regex=False)
    )
    return frame.loc[mask.any(axis=1)]


def render_table(
    rows: Iterable[dict[str, Any]],
    *,
    key: str,
    title: str | None = None,
    download_name: str | None = None,
    max_rows: int | None = None,
    total_count: int | None = None,
    total_label: str = "registros",
) -> pd.DataFrame:
    """Render a searchable table and offer the currently visible rows as CSV."""
    frame = dataframe_from(rows)
    source_count = len(frame) if total_count is None else total_count
    if title:
        st.subheader(title)
    if frame.empty:
        st.info("Não há dados para esta visão.")
        return frame
    st.markdown('<p class="table-filter-label">Filtrar tabela</p>', unsafe_allow_html=True)
    search = st.text_input(
        "Filtrar tabela",
        key=f"search_{key}",
        placeholder="Digite texto para buscar",
        label_visibility="collapsed",
    )
    visible = filter_frame(frame, search)
    filtered_count = len(visible)
    if total_count is not None or total_label != "registros":
        st.caption(
            f"Total: {source_count:,} {total_label}. "
            f"Após o filtro: {filtered_count:,} registros."
        )
    if max_rows is not None and len(visible) > max_rows:
        st.caption(f"Exibindo as primeiras {max_rows} de {len(visible)} linhas filtradas.")
        visible = visible.head(max_rows)
    st.dataframe(visible, width="stretch", hide_index=True)
    st.download_button(
        "Baixar tabela filtrada (CSV)",
        data=visible.to_csv(index=False).encode("utf-8-sig"),
        file_name=download_name or f"{key}.csv",
        mime="text/csv",
        key=f"download_{key}",
    )
    return visible


def render_overview(paths: WorkspacePaths, config, projects) -> None:
    page_header(
        "Architecture Generation Workbench",
        "Explore evidências estáticas, configure experimentos e compare prompt direto com fluxo agente.",
    )
    overview_rows = static_project_overview(paths)
    try:
        generated_runs, discovery_issues = run_records(paths.outputs_dir)
    except Exception as exc:  # noqa: BLE001
        generated_runs, discovery_issues = [], [{"message": str(exc)}]

    totals = {
        field: sum(numeric_value(row.get(field, 0)) for row in overview_rows)
        for field in ("classes", "packages", "entrypoints", "internal_package_dependencies")
    }
    cards = st.columns(6)
    cards[0].metric("Projetos", len(projects))
    cards[1].metric("Classes analisadas", f"{totals['classes']:,}")
    cards[2].metric("Pacotes", f"{totals['packages']:,}")
    cards[3].metric("Entrypoints", f"{totals['entrypoints']:,}")
    cards[4].metric(
        "Arestas internas",
        f"{totals['internal_package_dependencies']:,}",
        help="Dependências distintas entre pacotes inferidas por imports; não são chamadas em runtime.",
    )
    cards[5].metric("Execuções descobertas", len(generated_runs))

    left, right = st.columns((1.35, 1))
    with left:
        st.subheader("Panorama de análise estática")
        if overview_rows:
            frame = dataframe_from(overview_rows)
            chart_options = {
                "Classes": "classes",
                "Pacotes": "packages",
                "Entrypoints": "entrypoints",
                "Arestas internas de import": "internal_package_dependencies",
            }
            available_chart_options = {
                label: column for label, column in chart_options.items() if column in frame
            }
            for column in available_chart_options.values():
                frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
            if available_chart_options and "project" in frame:
                st.markdown(
                    '<p class="table-filter-label">Métrica no panorama</p>',
                    unsafe_allow_html=True,
                )
                chart_label = st.selectbox(
                    "Métrica no panorama",
                    list(available_chart_options),
                    key="overview_chart_metric",
                    label_visibility="collapsed",
                )
                chart_column = available_chart_options[chart_label]
                st.bar_chart(frame.set_index("project")[[chart_column]], height=290)
            render_table(
                overview_rows,
                key="overview_projects",
                title="Projetos disponíveis",
                download_name="project_summaries.csv",
            )
        else:
            st.warning("Não foi encontrado `project_summaries.csv` para o panorama agregado.")
    with right:
        st.subheader("Provedores configurados")
        providers = provider_rows(config)
        provider_frame = dataframe_from(providers)
        if not provider_frame.empty:
            visible_columns = [
                "provider",
                "enabled",
                "api_key_configured",
                "models",
                "base_url",
            ]
            st.dataframe(provider_frame[visible_columns], width="stretch", hide_index=True)
        if not generated_runs:
            st.info(
                "Ainda não há resultados em `outputs/`. Use “Executar experimentos” para gerar "
                "uma condição ou as duas estratégias."
            )
        else:
            ready = sum(1 for row in generated_runs if row["csv_exists"])
            traces = sum(1 for row in generated_runs if row["trace_exists"])
            st.metric("CSVs de arquitetura disponíveis", ready)
            st.metric("Traces disponíveis", traces)
        if discovery_issues:
            st.warning(f"Foram encontrados {len(discovery_issues)} avisos na descoberta de resultados.")

    st.markdown(
        '<div class="section-note"><strong>Como usar:</strong> comece por “Projetos e análise estática”, '
        "confira os prompts, rode uma condição em modo seco e então execute as duas abordagens.</div>",
        unsafe_allow_html=True,
    )


def select_project_snapshot(
    paths: WorkspacePaths,
    config,
    projects,
    *,
    key: str,
    accent_label: bool = False,
) -> ProjectSnapshot | None:
    if not projects:
        st.error("Nenhum projeto foi encontrado em `systems/`.")
        return None
    if accent_label:
        st.markdown('<p class="table-filter-label">Projeto</p>', unsafe_allow_html=True)
    selected_name = st.selectbox(
        "Projeto",
        [project.name for project in projects],
        key=key,
        label_visibility="collapsed" if accent_label else "visible",
    )
    try:
        return load_project_snapshot(paths, config, selected_name)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Não foi possível carregar os artefatos de `{selected_name}`: {exc}")
        return None


def render_static_analysis(paths: WorkspacePaths, config, projects) -> None:
    page_header(
        "Projetos e análise estática",
        "Os dados representam análise de código-fonte e imports; não são um call graph de execução.",
    )
    render_static_analysis_runner(paths)
    snapshot = select_project_snapshot(
        paths,
        config,
        projects,
        key="static_project",
        accent_label=True,
    )
    if snapshot is None:
        return
    static = snapshot.static_analysis
    summary = static.summary or {}
    totals = static_analysis_totals(static)
    metadata_columns = st.columns(6)
    for column, (label, field, help_text) in zip(
        metadata_columns,
        (
            ("Arquivos de build", "build_files", "pom.xml e/ou build.gradle detectados; não representa módulos de negócio."),
            ("Classes", "classes", "Classes encontradas nos fontes analisados."),
            ("Pacotes", "packages", "Pacotes de código-fonte detectados."),
            ("Entrypoints", "entrypoints", "Entrypoints inferidos heuristicamente pelo analisador."),
            ("Arestas internas", "internal_package_dependencies", "Dependências distintas entre pacotes inferidas por imports; não são chamadas de runtime."),
            ("Arestas externas", "external_package_dependencies", "Dependências externas inferidas por imports; não são chamadas de runtime."),
        ),
    ):
        value = totals.get(field)
        display_value = value if value is not None else "—"
        if field == "build_files":
            column.markdown(
                (
                    '<div class="static-build-metric">'
                    f'<div class="static-build-metric__label">{label}</div>'
                    f'<div class="static-build-metric__value">{display_value}</div>'
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
        else:
            column.metric(label, display_value, help=help_text)

    render_static_project_totals(totals, requirements_count=snapshot.requirements.row_count)

    methodology = summary.get("methodology", {}) if isinstance(summary, dict) else {}
    notes = methodology.get("notes", []) if isinstance(methodology, dict) else []
    if notes:
        st.info(" ".join(str(note) for note in notes))

    tabs = st.tabs(
        [
            "Resumo",
            "Requisitos",
            "Módulos",
            "Pacotes",
            "Dependências",
            "Entrypoints",
            "Classes",
            "Referência",
            "Outros artefatos",
        ]
    )
    with tabs[0]:
        render_static_summary(static, totals)
    with tabs[1]:
        st.caption(f"Arquivo detectado: `{snapshot.requirements.file_path.relative_to(paths.root).as_posix()}`")
        render_table(
            snapshot.requirements.rows,
            key=f"requirements_{snapshot.context.name}",
            title=f"Requisitos ({snapshot.requirements.row_count})",
            download_name=f"{snapshot.context.name}_requirements.csv",
            total_count=snapshot.requirements.row_count,
            total_label="requisitos",
        )
    with tabs[2]:
        render_table(
            static.modules,
            key=f"modules_{snapshot.context.name}",
            title="Módulos e arquivos de build",
            download_name=f"{snapshot.context.name}_modules.csv",
            total_count=totals.get("build_files"),
            total_label="arquivos de build / módulos detectados",
        )
    with tabs[3]:
        render_package_metrics(static.package_metrics, snapshot.context.name, totals)
    with tabs[4]:
        render_dependencies(static.package_dependencies, snapshot.context.name, totals)
    with tabs[5]:
        render_table(
            static.entrypoints,
            key=f"entrypoints_{snapshot.context.name}",
            title="Entrypoints detectados heuristicamente",
            download_name=f"{snapshot.context.name}_entrypoints.csv",
            total_count=totals.get("entrypoints"),
            total_label="entrypoints",
        )
    with tabs[6]:
        render_table(
            static.classes,
            key=f"classes_{snapshot.context.name}",
            title="Classes e papéis inferidos",
            download_name=f"{snapshot.context.name}_classes.csv",
            max_rows=1_000,
            total_count=totals.get("classes"),
            total_label="classes / tipos analisados",
        )
    with tabs[7]:
        reference_files = ground_truth_files(paths, snapshot.context.name)
        if not reference_files:
            st.info("Não há uma arquitetura de referência disponível para este projeto.")
        else:
            st.info(
                "A referência é apresentada apenas para consulta. O comparador atual não calcula "
                "precisão/recall contra ela automaticamente."
            )
            for reference in reference_files:
                with st.expander(reference.name, expanded=True):
                    reference_rows = read_csv_rows(reference)
                    render_table(
                        reference_rows,
                        key=f"ground_truth_{snapshot.context.name}_{reference.stem}",
                        download_name=reference.name,
                        total_count=len(reference_rows),
                        total_label="registros de referência",
                    )
    with tabs[8]:
        if not static.extras:
            st.info("Não há artefatos adicionais para este projeto.")
        for artifact in static.extras:
            with st.expander(artifact.path.name, expanded=False):
                if isinstance(artifact.content, list):
                    render_table(
                        artifact.content,
                        key=f"extra_{snapshot.context.name}_{artifact.path.stem}",
                        download_name=artifact.path.name,
                        total_count=artifact.row_count,
                        total_label="registros",
                    )
                elif isinstance(artifact.content, dict):
                    st.caption(f"Total: {artifact.row_count:,} campos no objeto JSON.")
                    st.json(artifact.content)
                else:
                    text = str(artifact.content)
                    st.caption(
                        f"Total: {artifact.row_count:,} linhas e {len(text):,} caracteres."
                    )
                    if len(text) > 50_000:
                        st.warning("A prévia foi truncada em 50.000 caracteres.")
                        text = text[:50_000] + "\n\n[preview truncated]"
                    st.code(text, language="text")


def render_static_analysis_runner(paths: WorkspacePaths) -> None:
    """Expose the repository's existing all-project analyzer behind explicit confirmation."""
    with st.expander("Atualizar a análise estática dos oito projetos"):
        st.info(
            "Esta ação reprocessa todos os projetos em `systems/` e sobrescreve os artefatos em "
            "`analysis-results/static-analysis/`. Ela não chama um LLM."
        )
        try:
            command = build_static_analysis_command(paths)
        except FileNotFoundError as exc:
            st.error(str(exc))
            return
        st.code(format_command(command), language="powershell")
        confirmed = st.checkbox(
            "Confirmo que quero atualizar os resultados de análise estática.",
            key="confirm_static_analysis",
        )
        if st.button(
            "Executar análise estática",
            type="primary",
            disabled=not confirmed,
            key="run_static_analysis",
        ):
            try:
                with st.status("Analisando todos os projetos...", expanded=True) as status:
                    with exclusive_job_lock(paths.root, name="workbench"):
                        result = run_local_command(command, paths.root)
                    log = "\n".join(
                        part
                        for part in (
                            "STDOUT:\n" + result.stdout.strip() if result.stdout.strip() else "",
                            "STDERR:\n" + result.stderr.strip() if result.stderr.strip() else "",
                        )
                        if part
                    )
                    if log:
                        st.code(log, language="text")
                    if result.output_truncated:
                        st.warning("Os logs exibidos foram truncados em 1 MB por fluxo.")
                    if result.return_code == 0:
                        status.update(label="Análise estática concluída", state="complete")
                        st.success("Resultados atualizados. Use o botão lateral “Atualizar dados” para recarregar as tabelas.")
                    else:
                        label = "A análise estática excedeu o tempo limite" if result.timed_out else "A análise estática terminou com erro"
                        status.update(label=label, state="error")
            except RuntimeError as exc:
                st.error(str(exc))


def render_static_project_totals(
    totals: dict[str, int | None], *, requirements_count: int
) -> None:
    """Show every reliable project-level total without treating unknown values as zero."""

    groups = (
        (
            "Arquivos e evidências",
            (
                ("Requisitos", requirements_count, "Linhas não vazias do CSV de requisitos."),
                ("Arquivos de build", totals.get("build_files"), "pom.xml e build.gradle detectados."),
                (
                    "Submódulos declarados",
                    totals.get("declared_submodules"),
                    "Submódulos declarados em arquivos de build; Gradle pode não os declarar dessa forma.",
                ),
                ("Raízes de fonte", totals.get("source_roots"), "Diretórios Java identificados."),
                (
                    "Arquivos Java",
                    totals.get("java_files"),
                    "Inclui package-info.java e module-info.java quando existirem.",
                ),
                (
                    "Tipos analisados",
                    totals.get("analyzed_type_files"),
                    "Arquivos Java analisados como classe, interface, enum, record ou anotação.",
                ),
                (
                    "Descritores Java",
                    totals.get("java_descriptor_files"),
                    "Arquivos package-info.java ou module-info.java não contabilizados como tipo analisado.",
                ),
            ),
        ),
        (
            "Código",
            (
                ("Classes/tipos", totals.get("classes"), "Tipos Java analisados."),
                ("Classes main", totals.get("main_classes"), "Tipos do conjunto de fontes main."),
                ("Classes de teste", totals.get("test_classes"), "Tipos do conjunto de testes."),
                ("Classes de UI test", totals.get("ui_test_classes"), "Tipos do conjunto de testes de interface."),
                ("Métodos", totals.get("methods"), "Métodos e construtores inferidos heuristicamente."),
                (
                    "Métodos públicos",
                    totals.get("public_methods"),
                    "Métodos inferidos com modificador public.",
                ),
                ("Linhas de fonte", totals.get("source_lines"), "Linhas em tipos Java analisados."),
                (
                    "Linhas efetivas",
                    totals.get("effective_source_lines"),
                    "Linhas não vazias após a remoção de comentários.",
                ),
            ),
        ),
        (
            "Estrutura",
            (
                ("Pacotes", totals.get("packages"), "Pacotes de código-fonte detectados."),
                (
                    "Raízes de pacote",
                    totals.get("package_roots"),
                    "Agrupamentos dos três primeiros segmentos do pacote; o resumo lista no máximo dez.",
                ),
                ("Papéis inferidos", totals.get("inferred_roles"), "Categorias de papel identificadas."),
                ("Tipos de declaração", totals.get("type_kinds"), "Class, interface, enum, record ou anotação."),
                (
                    "Entrypoints",
                    totals.get("entrypoints"),
                    "Entrypoints inferidos heuristicamente; não são confirmação de execução em runtime.",
                ),
            ),
        ),
        (
            "Imports e dependências",
            (
                ("Imports", totals.get("imports"), "Declarações import encontradas nos tipos analisados."),
                ("Imports internos", totals.get("internal_imports"), "Imports classificados como internos."),
                ("Imports externos", totals.get("external_imports"), "Imports classificados como externos."),
                (
                    "Arestas entre pacotes",
                    totals.get("package_dependency_edges"),
                    "Pares distintos origem → destino inferidos por imports.",
                ),
                (
                    "Arestas internas",
                    totals.get("internal_package_dependencies"),
                    "Arestas distintas entre pacotes internos; não são chamadas de runtime.",
                ),
                (
                    "Arestas externas",
                    totals.get("external_package_dependencies"),
                    "Arestas distintas para pacotes externos; não são chamadas de runtime.",
                ),
                (
                    "Ocorrências internas",
                    totals.get("internal_package_dependency_occurrences"),
                    "Soma dos pesos das arestas internas entre pacotes.",
                ),
                (
                    "Ocorrências externas",
                    totals.get("external_package_dependency_occurrences"),
                    "Soma dos pesos das arestas externas entre pacotes.",
                ),
                (
                    "Raízes externas",
                    totals.get("external_dependency_roots"),
                    "Raízes de dependências externas; o resumo lista no máximo vinte.",
                ),
            ),
        ),
    )

    with st.container(border=True, key="static_project_totals"):
        st.subheader("Totais detalhados do projeto")
        st.caption("Os totais são calculados pelos artefatos disponíveis. Campos sem base confiável não são exibidos.")
        for group_name, metrics in groups:
            available_metrics = [metric for metric in metrics if metric[1] is not None]
            if not available_metrics:
                continue
            st.markdown(
                f'<p class="static-total-group-heading">{escape(group_name)}</p>',
                unsafe_allow_html=True,
            )
            for start in range(0, len(available_metrics), 4):
                row = available_metrics[start : start + 4]
                columns = st.columns(len(row))
                for column, (label, value, help_text) in zip(columns, row):
                    column.metric(label, f"{value:,}", help=help_text)


def render_static_summary(static, totals: dict[str, int | None]) -> None:
    summary = static.summary or {}
    left, right = st.columns((1, 1.25))
    with left:
        st.subheader("Metadados")
        st.json(
            {
                "project": summary.get("project", ""),
                "generated_at_utc": summary.get("generated_at_utc", ""),
                "build_tools": summary.get("build_tools", []),
                "counts": summary.get("counts", {}),
                "source_roots": summary.get("source_roots", []),
                "package_roots": summary.get("package_roots", []),
            }
        )
    with right:
        roles = summary.get("role_counts", {}) if isinstance(summary, dict) else {}
        st.subheader("Papéis inferidos")
        if roles:
            role_frame = dataframe_from(
                {"papel": role, "classes": count} for role, count in roles.items()
            ).sort_values("classes", ascending=False)
            st.caption(
                f"Total: {sum(numeric_value(count) for count in roles.values()):,} classes/tipos "
                f"em {len(role_frame):,} papéis."
            )
            st.bar_chart(role_frame.set_index("papel"), height=240)
        else:
            st.info("A análise não forneceu distribuição de papéis.")

    top_internal = summary.get("top_internal_dependencies", []) if isinstance(summary, dict) else []
    if top_internal:
        render_table(
            top_internal,
            key="summary_internal_dependencies",
            title="Principais dependências internas",
            download_name="top_internal_dependencies.csv",
            total_count=totals.get("internal_package_dependencies"),
            total_label="arestas internas de dependência",
        )
    top_external = summary.get("top_external_dependency_roots", []) if isinstance(summary, dict) else []
    if top_external:
        st.subheader("Dependências externas frequentes")
        external_frame = dataframe_from(top_external)
        if {"dependency_root", "count"}.issubset(external_frame.columns):
            external_frame["count"] = pd.to_numeric(external_frame["count"], errors="coerce").fillna(0)
            occurrences = totals.get("external_package_dependency_occurrences")
            root_count = totals.get("external_dependency_roots")
            if occurrences is not None and root_count is not None:
                st.caption(
                    f"Exibindo até 20 de {root_count:,} raízes externas; "
                    f"{occurrences:,} ocorrências de import externo entre pacotes."
                )
            st.bar_chart(
                external_frame.sort_values("count", ascending=False)
                .head(20)
                .set_index("dependency_root")[["count"]],
                height=280,
            )


def render_package_metrics(
    rows: list[dict[str, str]], project_name: str, totals: dict[str, int | None]
) -> None:
    if not rows:
        st.info("Não há métricas de pacotes neste artefato.")
        return
    frame = dataframe_from(rows)
    numeric_columns = [
        "class_count",
        "method_count",
        "public_method_count",
        "incoming_internal_dependencies",
        "outgoing_internal_dependencies",
    ]
    for column in numeric_columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    if {
        "incoming_internal_dependencies",
        "outgoing_internal_dependencies",
    }.issubset(frame.columns):
        frame["internal_coupling"] = (
            frame["incoming_internal_dependencies"] + frame["outgoing_internal_dependencies"]
        )
    chart_options = {
        "Classes": "class_count",
        "Métodos": "method_count",
        "Métodos públicos": "public_method_count",
        "Volume de imports internos": "internal_coupling",
    }
    available_options = {
        label: column for label, column in chart_options.items() if column in frame.columns
    }
    if available_options and "package" in frame:
        st.markdown(
            '<p class="package-chart-label">Métrica exibida no gráfico</p>',
            unsafe_allow_html=True,
        )
        selected_label = st.selectbox(
            "Métrica exibida no gráfico",
            list(available_options),
            key=f"package_metric_chart_{project_name}",
            label_visibility="collapsed",
        )
        selected_column = available_options[selected_label]
        st.subheader(f"Pacotes com maior valor: {selected_label}")
        if selected_column == "internal_coupling":
            st.caption("Volume de imports internos de entrada + saída; não mede tráfego ou chamadas em runtime.")
        st.bar_chart(
            frame.sort_values(selected_column, ascending=False)
            .head(20)
            .set_index("package")[[selected_column]],
            height=300,
        )
    render_table(
        frame.to_dict("records"),
        key=f"package_metrics_{project_name}",
        title="Métricas por pacote",
        download_name=f"{project_name}_package_metrics.csv",
        total_count=totals.get("packages"),
        total_label="pacotes",
    )


def render_dependencies(
    rows: list[dict[str, str]], project_name: str, totals: dict[str, int | None]
) -> None:
    if not rows:
        st.info("Não há dependências de pacote neste artefato.")
        return
    categories = sorted({row.get("category", "") for row in rows if row.get("category", "")})
    controls = st.columns((1, 1, 2))
    category = controls[0].selectbox(
        "Categoria", ["all", *categories], key=f"dependency_category_{project_name}"
    )
    min_count = controls[1].number_input(
        "Peso mínimo", min_value=1, value=1, step=1, key=f"dependency_weight_{project_name}"
    )
    filtered = [
        row
        for row in rows
        if (category in {"all", ""} or row.get("category", "") == category)
        and numeric_value(row.get("count", 0)) >= min_count
    ]
    filtered.sort(key=lambda row: (-numeric_value(row.get("count", 0)), row.get("source_package", "")))
    filtered_weight = sum(numeric_value(row.get("count", 0)) for row in filtered)
    total_weight = sum(numeric_value(row.get("count", 0)) for row in rows)
    total_edges = totals.get("package_dependency_edges")
    st.caption(
        f"Total do projeto: {(total_edges if total_edges is not None else len(rows)):,} arestas "
        f"com peso {total_weight:,}. Após o filtro: {len(filtered):,} arestas com peso "
        f"{filtered_weight:,}. As arestas são inferidas por imports; o peso representa "
        "ocorrências de import, não chamadas em runtime."
    )
    if category in {"internal", "all"}:
        internal = [row for row in filtered if row.get("category") == "internal"][:40]
        if internal:
            st.subheader("Grafo de dependências internas (até 40 arestas)")
            try:
                st.graphviz_chart(dependency_dot(internal), width="stretch")
            except Exception as exc:  # noqa: BLE001
                st.info(f"Não foi possível renderizar o grafo: {exc}")
    render_table(
        filtered,
        key=f"dependencies_{project_name}",
        title="Arestas de dependência",
        download_name=f"{project_name}_package_dependencies.csv",
        max_rows=1_000,
        total_count=total_edges,
        total_label="arestas de dependência",
    )


def dependency_dot(rows: list[dict[str, Any]]) -> str:
    """Create a compact directed DOT graph from trusted static-analysis rows."""
    lines = [
        "digraph dependencies {",
        "rankdir=LR;",
        'graph [bgcolor="transparent", pad="0.2"];',
        'node [shape=box, style="rounded,filled", fillcolor="#eaf0ff", color="#4d6eb5", fontname="Arial", fontsize=10];',
        'edge [color="#647aa8", fontname="Arial", fontsize=9];',
    ]
    for row in rows:
        source = dot_escape(str(row.get("source_package", "")))
        target = dot_escape(str(row.get("target_package", "")))
        count = numeric_value(row.get("count", 0))
        if source and target:
            lines.append(f'"{source}" -> "{target}" [label=" {count} ", penwidth=1.5];')
    lines.append("}")
    return "\n".join(lines)


def dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_direct_prompts(paths: WorkspacePaths, config, projects) -> None:
    page_header(
        "Estratégia por prompt direto",
        "Prévia exata do system prompt, do user prompt e das evidências que serão enviados ao modelo.",
    )
    snapshot = select_project_snapshot(
        paths,
        config,
        projects,
        key="prompt_project",
        accent_label=True,
    )
    if snapshot is None:
        return
    templates = config.experiment.prompt_templates
    if not templates:
        st.error("Nenhum template de prompt está configurado em `config.yaml`.")
        return
    st.markdown('<p class="direct-prompt-label">Template de prompt</p>', unsafe_allow_html=True)
    template = st.selectbox(
        "Template de prompt",
        templates,
        key="prompt_template_preview",
        label_visibility="collapsed",
    )
    try:
        prompt = build_prompt(
            project_name=snapshot.context.name,
            requirements=snapshot.requirements,
            static_analysis=snapshot.static_analysis,
            template_name=template,
            limits=config.experiment.prompt_limits,
        )
        evidence = build_evidence_context(
            project_name=snapshot.context.name,
            requirements=snapshot.requirements,
            static_analysis=snapshot.static_analysis,
            limits=config.experiment.prompt_limits,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Não foi possível construir o prompt: {exc}")
        return

    cards = st.columns(4)
    for column, label, value in zip(
        cards,
        ("Template", "System prompt", "User prompt", "Evidências"),
        (
            template,
            f"{len(prompt.system_prompt):,} caracteres",
            f"{len(prompt.user_prompt):,} caracteres",
            f"{len(evidence):,} caracteres",
        ),
        strict=True,
    ):
        column.markdown(
            (
                '<div class="direct-prompt-metric">'
                f'<div class="direct-prompt-metric__label">{escape(label)}</div>'
                f'<div class="direct-prompt-metric__value">{escape(value)}</div>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )
    if template == "few_shot":
        st.info(
            "O template few-shot contém três exemplos genéricos. Eles mostram que módulos e "
            "pacotes são evidência estrutural, não uma regra de N módulos para N serviços."
        )

    tabs = st.tabs(["System prompt", "User prompt", "Evidências", "Schema esperado"])
    with tabs[0]:
        st.code(prompt.system_prompt, language="text")
    with tabs[1]:
        st.code(prompt.user_prompt, language="text")
    with tabs[2]:
        st.code(evidence, language="text")
    with tabs[3]:
        st.code(JSON_SCHEMA_SNIPPET, language="json")
        if template == "few_shot":
            with st.expander("Ver os exemplos few-shot completos"):
                st.code(FEW_SHOT_EXAMPLES, language="text")
    st.download_button(
        "Baixar prévia completa do prompt",
        data=render_prompt_text(prompt).encode("utf-8"),
        file_name=f"{snapshot.context.name}_{template}_prompt.txt",
        mime="text/plain",
    )


def render_agent_flow(paths: WorkspacePaths, config, projects) -> None:
    page_header(
        "Fluxo da estratégia por agente",
        "O agente separa a leitura do domínio da leitura estrutural antes de sintetizar, criticar e refinar a arquitetura.",
    )
    max_rounds = config.experiment.agent.max_refinement_rounds
    minimum_calls = minimum_agent_calls()
    maximum_calls = maximum_agent_calls(config)
    retry_ceiling = maximum_agent_calls(
        config,
        max_attempts=config.experiment.max_attempts,
    )
    cards = st.columns(3)
    cards[0].metric("Papéis especializados", 5)
    cards[1].metric("Rodadas máximas de refinamento", max_rounds)
    cards[2].metric("Chamadas LLM sem repetição", f"{minimum_calls}–{maximum_calls}")

    st.markdown("### Fluxo de decisão")
    flow_columns = st.columns(5)
    flow_steps = (
        ("1", "Analista de domínio", "Capacidades, entidades e regras suportadas pelas evidências."),
        ("2", "Analista estrutural", "Módulos, clusters de código, entrypoints e riscos de acoplamento."),
        ("3", "Arquiteto", "Concilia as duas análises e registra o snapshot candidato."),
        ("4", "Crítico", "Decide se há um defeito material sustentado por evidências."),
        ("5", "Refinador", "Só é chamado quando o crítico pede revisão; então volta ao crítico."),
    )
    for column, (number, title, description) in zip(flow_columns, flow_steps):
        column.markdown(
            f'<div class="flow-step"><strong>{number}. {title}</strong><br><br>{description}</div>',
            unsafe_allow_html=True,
        )
    st.caption(
        "As análises de domínio e estrutural ocorrem sequencialmente na implementação atual. "
        "O fluxo encerra quando o crítico aprova ou o limite de refinamentos é alcançado. "
        f"Com até {config.experiment.max_attempts} tentativas por papel, o teto é {retry_ceiling} requisições à API."
    )

    snapshot = select_project_snapshot(
        paths,
        config,
        projects,
        key="agent_project",
        accent_label=True,
    )
    if snapshot is None:
        return
    templates = config.experiment.prompt_templates
    if not templates:
        st.error("Nenhum template de prompt está configurado em `config.yaml`.")
        return
    st.markdown('<p class="direct-prompt-label">Template para a síntese</p>', unsafe_allow_html=True)
    template = st.selectbox(
        "Template para a síntese",
        templates,
        key="agent_template",
        label_visibility="collapsed",
    )
    evidence = build_evidence_context(
        project_name=snapshot.context.name,
        requirements=snapshot.requirements,
        static_analysis=snapshot.static_analysis,
        limits=config.experiment.prompt_limits,
    )
    tabs = st.tabs(["Prompts iniciais", "Prompts de papéis", "Trace de uma execução"])
    with tabs[0]:
        prompt_tabs = st.tabs(["Domínio", "Estrutura", "Evidências"])
        with prompt_tabs[0]:
            st.code(build_domain_prompt(evidence), language="text")
        with prompt_tabs[1]:
            st.code(build_structural_prompt(evidence), language="text")
        with prompt_tabs[2]:
            st.code(evidence, language="text")
    with tabs[1]:
        role_prompts = {
            "domain_analyst": DOMAIN_SYSTEM_PROMPT,
            "structural_analyst": STRUCTURAL_SYSTEM_PROMPT,
            "architect": ARCHITECT_SYSTEM_PROMPT,
            "critic": CRITIC_SYSTEM_PROMPT,
            "refiner": REFINER_SYSTEM_PROMPT,
        }
        for role, system_prompt in role_prompts.items():
            with st.expander(role.replace("_", " ").title()):
                st.code(system_prompt, language="text")
        st.info(
            f"O template `{template}` é usado na síntese. Os prompts de crítica e refinamento "
            "incluem respostas intermediárias; por isso são visíveis integralmente no trace após uma execução."
        )
    with tabs[2]:
        render_agent_trace_picker(paths)


def render_execution(paths: WorkspacePaths, config, projects) -> None:
    page_header(
        "Executar experimentos",
        "Escolha condições existentes na configuração. A interface preserva o CLI atual e não usa shell para iniciar processos.",
    )
    project_names = [project.name for project in projects]
    provider_configurations = {
        name: provider for name, provider in config.providers.items() if provider.enabled
    }
    if not project_names or not provider_configurations:
        st.error("Não há projetos ou provedores habilitados suficientes para uma execução.")
        return

    select_all_projects = st.checkbox("Executar para todos os projetos", value=False)
    selected_projects = (
        project_names
        if select_all_projects
        else None
    )
    if selected_projects is None:
        st.markdown('<p class="direct-prompt-label">Projetos</p>', unsafe_allow_html=True)
        selected_projects = st.multiselect(
            "Projetos",
            project_names,
            default=project_names[:1],
            label_visibility="collapsed",
        )
    st.markdown('<p class="direct-prompt-label">Provedor</p>', unsafe_allow_html=True)
    provider_name = st.selectbox(
        "Provedor",
        list(provider_configurations),
        key="execution_provider",
        label_visibility="collapsed",
    )
    provider = provider_configurations[provider_name]
    model_options = [model.name for model in provider.models]
    if not model_options:
        st.error(f"O provedor `{provider_name}` não possui modelos configurados.")
        return
    st.markdown('<p class="direct-prompt-label">Modelo</p>', unsafe_allow_html=True)
    model_name = st.selectbox(
        "Modelo",
        model_options,
        key="execution_model",
        label_visibility="collapsed",
    )
    st.markdown('<p class="direct-prompt-label">Abordagens</p>', unsafe_allow_html=True)
    approaches = st.multiselect(
        "Abordagens",
        ["direct", "agent"],
        default=["direct", "agent"],
        help="O fluxo agente faz múltiplas chamadas e pode pedir refinamentos.",
        label_visibility="collapsed",
    )
    st.markdown('<p class="direct-prompt-label">Templates de prompt</p>', unsafe_allow_html=True)
    templates = st.multiselect(
        "Templates de prompt",
        config.experiment.prompt_templates,
        default=config.experiment.prompt_templates,
        label_visibility="collapsed",
    )
    settings = st.columns(4)
    settings[0].markdown('<p class="direct-prompt-label">Repetições por condição</p>', unsafe_allow_html=True)
    runs = int(settings[0].number_input("Repetições por condição", min_value=1, max_value=20, value=config.experiment.default_runs, label_visibility="collapsed"))
    settings[1].markdown('<p class="direct-prompt-label">Máximo de tentativas</p>', unsafe_allow_html=True)
    max_attempts = int(settings[1].number_input("Máximo de tentativas", min_value=1, max_value=10, value=config.experiment.max_attempts, label_visibility="collapsed"))
    settings[2].markdown('<p class="direct-prompt-label">Modo seco</p>', unsafe_allow_html=True)
    dry_run = settings[2].checkbox("Modo seco", value=True, help="Monta prompts e valida descoberta, sem chamar a API.", label_visibility="collapsed")
    settings[3].markdown('<p class="direct-prompt-label">Salvar prompts</p>', unsafe_allow_html=True)
    save_prompts = settings[3].checkbox("Salvar prompts", value=True, label_visibility="collapsed")
    st.markdown('<p class="direct-prompt-label">Diretório de saída (dentro de outputs/)</p>', unsafe_allow_html=True)
    output_directory_text = st.text_input(
        "Diretório de saída (dentro de outputs/)",
        value=active_outputs_value(),
        key="execution_output_dir",
        label_visibility="collapsed",
    )

    try:
        output_dir = resolve_managed_path(paths.root, output_directory_text, paths.outputs_dir)
        commands = [
            build_generation_command(
                project_name=project_name,
                provider_name=provider_name,
                model_name=model_name,
                approaches=approaches,
                prompt_templates=templates,
                runs=runs,
                max_attempts=max_attempts,
                output_dir=output_dir,
                dry_run=dry_run,
                save_prompts=save_prompts,
            )
            for project_name in selected_projects
        ]
        configuration_error = ""
    except ValueError as exc:
        commands = []
        configuration_error = str(exc)

    condition_count = len(selected_projects) * len(approaches) * len(templates) * runs
    st.markdown(
        f'<div class="section-note"><strong>Plano:</strong> {condition_count} condição(ões) serão processadas. '
        f"O agente usa de {minimum_agent_calls()} a {maximum_agent_calls(config)} chamadas sem repetição "
        f"e até {maximum_agent_calls(config, max_attempts=max_attempts)} requisições com o limite de tentativas escolhido; "
        f"o prompt direto faz de 1 a {max_attempts} requisições.</div>",
        unsafe_allow_html=True,
    )
    if configuration_error:
        st.error(configuration_error)
        return
    if not commands:
        st.warning("Selecione ao menos um projeto, uma abordagem e um template.")
        return

    st.subheader("Prévia dos comandos")
    st.code("\n\n".join(format_command(command) for command in commands), language="powershell")
    api_key_ready = bool(__import__("os").getenv(provider.api_key_env))
    if dry_run:
        st.info("Modo seco ativo: nenhuma chamada será enviada ao provedor. O CLI ainda registra a condição em metadata.csv.")
    elif not api_key_ready:
        st.error(
            f"A variável de ambiente `{provider.api_key_env}` não foi encontrada. Configure-a antes de executar uma chamada real."
        )
    else:
        st.info(
            "Execuções reais podem gerar custo e sobrescrever CSV/trace de uma condição já existente. "
            "O metadata preserva o histórico de tentativas."
        )
    confirmed = st.checkbox(
        "Confirmo que quero iniciar as execuções reais selecionadas.",
        disabled=dry_run,
    )
    action_label = "Validar e gerar prévias (modo seco)" if dry_run else "Iniciar execuções reais"
    can_run = bool(commands) and (dry_run or (confirmed and api_key_ready))
    if st.button(action_label, type="primary", disabled=not can_run, width="stretch"):
        st.session_state["active_outputs_dir"] = relative_workspace_path(paths, output_dir)
        try:
            results = execute_commands(commands, paths.root, selected_projects)
        except RuntimeError as exc:
            st.error(str(exc))
            return
        successful = sum(1 for result in results if result.return_code == 0)
        if successful == len(results):
            st.success("Processos concluídos. Atualize “Resultados gerados” para inspecionar os artefatos.")
        else:
            st.error("Uma ou mais execuções terminaram com erro. Consulte os logs abaixo e metadata.csv.")


def minimum_agent_calls() -> int:
    return 4


def maximum_agent_calls(config, *, max_attempts: int = 1) -> int:
    """Return the API-request ceiling for an agent workflow under the chosen retry limit."""
    logical_calls = 3 + (2 * config.experiment.agent.max_refinement_rounds)
    return logical_calls * max_attempts


def execute_commands(
    commands: list[list[str]], root: Path, project_names: list[str]
) -> list[CommandResult]:
    """Run selected CLI jobs sequentially so output paths never race each other."""
    results: list[CommandResult] = []
    progress = st.progress(0, text="Preparando execuções...")
    with exclusive_job_lock(root, name="workbench"):
        for index, (command, project_name) in enumerate(zip(commands, project_names), start=1):
            with st.status(f"Executando `{project_name}` ({index}/{len(commands)})", expanded=True) as status:
                st.code(format_command(command), language="powershell")
                result = run_local_command(command, root)
                results.append(result)
                combined_log = "\n".join(
                    section
                    for section in (
                        "STDOUT:\n" + result.stdout.strip() if result.stdout.strip() else "",
                        "STDERR:\n" + result.stderr.strip() if result.stderr.strip() else "",
                    )
                    if section
                )
                if combined_log:
                    st.code(combined_log, language="text")
                if result.output_truncated:
                    st.warning("Os logs exibidos foram truncados em 1 MB por fluxo.")
                if result.return_code == 0:
                    status.update(label=f"`{project_name}` concluído", state="complete")
                else:
                    label = (
                        f"`{project_name}` excedeu o tempo limite"
                        if result.timed_out
                        else f"`{project_name}` terminou com erro"
                    )
                    status.update(label=label, state="error")
            progress.progress(index / len(commands), text=f"Execução {index} de {len(commands)} concluída")
    return results


def render_generated_results(paths: WorkspacePaths, config, projects) -> None:
    page_header(
        "Resultados gerados",
        "Explore CSVs finais, métricas estruturais, prompts salvos e traces das duas abordagens.",
    )
    st.markdown(
        '<p class="direct-prompt-label">Diretório de saída (dentro de outputs/)</p>',
        unsafe_allow_html=True,
    )
    output_directory_text = st.text_input(
        "Diretório de saída (dentro de outputs/)",
        value=active_outputs_value(),
        key="results_output_dir",
        label_visibility="collapsed",
    )
    try:
        outputs_dir = resolve_managed_path(paths.root, output_directory_text, paths.outputs_dir)
        artifact_problems = validate_output_artifacts(outputs_dir)
        records, discovery_issues = run_records(outputs_dir)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Não foi possível descobrir resultados: {exc}")
        return
    if artifact_problems:
        st.error(
            "Algumas linhas de metadata apontam para fora do diretório selecionado. "
            "A interface não abrirá esses artefatos."
        )
        render_table(
            [{"problema": problem} for problem in artifact_problems],
            key="unsafe_result_artifacts",
            title="Caminhos bloqueados",
        )
    if not records:
        st.info(
            "Nenhuma execução foi encontrada. Use “Executar experimentos” em modo seco ou real; "
            "os resultados aparecerão aqui."
        )
        if discovery_issues:
            render_table(discovery_issues, key="empty_result_issues", title="Avisos de descoberta")
        return

    filtered_records = filter_run_records(records, prefix="results")
    render_table(filtered_records, key="generated_runs", title="Execuções descobertas", download_name="runs.csv")
    if discovery_issues:
        with st.expander(f"Avisos de descoberta ({len(discovery_issues)})"):
            render_table(discovery_issues, key="result_discovery_issues", download_name="discovery_issues.csv")
    if not filtered_records:
        return

    labels = [run_label(record) for record in filtered_records]
    st.markdown('<p class="direct-prompt-label">Inspecionar execução</p>', unsafe_allow_html=True)
    selected_index = st.selectbox(
        "Inspecionar execução",
        range(len(filtered_records)),
        format_func=lambda index: labels[index],
        label_visibility="collapsed",
    )
    record = filtered_records[selected_index]
    render_run_detail(record, paths)


def filter_run_records(records: list[dict[str, Any]], *, prefix: str) -> list[dict[str, Any]]:
    frame = dataframe_from(records)
    if frame.empty:
        return []
    controls = st.columns(5)
    filters: dict[str, str] = {}
    for column, label, control in zip(
        ("project_name", "approach", "provider", "model_name", "prompt_template"),
        ("Projeto", "Abordagem", "Provedor", "Modelo", "Template"),
        controls,
    ):
        values = sorted(value for value in frame[column].dropna().astype(str).unique() if value)
        control.markdown(
            f'<p class="direct-prompt-label">{escape(label)}</p>',
            unsafe_allow_html=True,
        )
        filters[column] = control.selectbox(
            label,
            ["Todos", *values],
            key=f"{prefix}_{column}",
            label_visibility="collapsed",
        )
    for column, selected in filters.items():
        if selected != "Todos":
            frame = frame[frame[column] == selected]
    return frame.to_dict("records")


def run_label(record: dict[str, Any]) -> str:
    return " · ".join(
        str(record.get(field, ""))
        for field in ("project_name", "approach", "provider", "model_name", "prompt_template", "run_id")
    )


def render_run_detail(record: dict[str, Any], paths: WorkspacePaths) -> None:
    st.divider()
    st.subheader(run_label(record))
    cards = st.columns(5)
    for column, label, value in zip(
        cards,
        ("Metadata", "CSV", "Trace", "Prompt salvo", "Registros metadata"),
        (
            record.get("metadata_status", ""),
            "disponível" if record.get("csv_exists") else "ausente",
            "disponível" if record.get("trace_exists") else "ausente",
            "sim" if record.get("prompt_exists") else "não",
            record.get("metadata_record_count", 0),
        ),
        strict=True,
    ):
        column.markdown(
            (
                '<div class="direct-prompt-metric">'
                f'<div class="direct-prompt-metric__label">{escape(label)}</div>'
                f'<div class="direct-prompt-metric__value">{escape(str(value))}</div>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )
    if record.get("metadata_error"):
        st.error(record["metadata_error"])
    if record.get("pairing_warnings"):
        st.info(record["pairing_warnings"])

    tabs = st.tabs(["Arquitetura", "Métricas", "Trace", "Prompt salvo"])
    csv_path = Path(record["csv_path"]) if record.get("csv_path") else None
    trace_path = Path(record["trace_path"]) if record.get("trace_path") else None
    prompt_path = Path(record["prompt_path"]) if record.get("prompt_path") else None
    with tabs[0]:
        if csv_path is None or not csv_path.exists():
            st.info("Não há CSV final para esta execução.")
        else:
            rows = read_csv_rows(csv_path)
            render_table(rows, key=f"architecture_{run_label(record)}", download_name=csv_path.name)
            try:
                architecture = analyze_architecture_csv(csv_path)
                if architecture.service_names:
                    st.subheader("Serviços e comunicações válidas")
                    st.graphviz_chart(
                        architecture_dot(architecture.service_names, architecture.valid_edges),
                        width="stretch",
                    )
                    if not architecture.valid_edges:
                        st.info("A proposta não declara comunicações válidas entre serviços.")
                else:
                    st.info("A proposta não declara comunicações válidas entre serviços.")
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Não foi possível analisar a estrutura do CSV: {exc}")
    with tabs[1]:
        render_run_metrics(csv_path, trace_path)
    with tabs[2]:
        render_trace(trace_path, key=f"trace_{run_label(record)}")
    with tabs[3]:
        if prompt_path is None or not prompt_path.exists():
            st.info("O prompt não foi salvo para esta execução.")
        else:
            text, truncated = read_limited_text(prompt_path)
            if truncated:
                st.warning("A visualização foi truncada para proteger a interface; baixe o arquivo completo abaixo.")
            st.code(text, language="text")
            render_file_download(
                prompt_path,
                label="Baixar prompt completo",
                mime="text/plain",
                key=f"prompt_{run_label(record)}",
                sensitive=True,
            )


def render_run_metrics(csv_path: Path | None, trace_path: Path | None) -> None:
    architecture_metrics: dict[str, Any] = {}
    trace_metrics: dict[str, Any] = {}
    architecture_warnings: list[str] = []
    trace_warnings: list[str] = []
    if csv_path and csv_path.exists():
        try:
            architecture = analyze_architecture_csv(csv_path)
            architecture_metrics = architecture.metrics
            architecture_warnings = architecture.warnings
        except Exception as exc:  # noqa: BLE001
            architecture_warnings = [str(exc)]
    if trace_path and trace_path.exists():
        try:
            trace_metrics, trace_warnings = analyze_trace(
                trace_path,
                max_events=TRACE_PREVIEW_MAX_EVENTS,
                max_bytes=TRACE_PREVIEW_MAX_BYTES,
            )
        except Exception as exc:  # noqa: BLE001
            trace_warnings = [str(exc)]

    left, right = st.columns(2)
    with left:
        st.subheader("Métricas de arquitetura")
        if architecture_metrics:
            render_metric_json(architecture_metrics)
        else:
            st.info("Métricas indisponíveis sem um CSV válido.")
        for warning in architecture_warnings:
            st.warning(warning)
    with right:
        st.subheader("Métricas de processo")
        if trace_metrics:
            render_metric_json(trace_metrics)
        else:
            st.info("Métricas indisponíveis sem trace.")
        for warning in trace_warnings:
            st.warning(warning)


def render_metric_json(metrics: dict[str, Any]) -> None:
    frame = dataframe_from(
        {"métrica": key, "valor": value}
        for key, value in metrics.items()
        if key not in {"roles", "critic_issue_categories", "critic_issue_severities"}
    )
    st.dataframe(frame, width="stretch", hide_index=True, height=380)
    extras = {
        key: value
        for key, value in metrics.items()
        if key in {"roles", "critic_issue_categories", "critic_issue_severities", "run_status"}
    }
    if extras:
        st.caption(json.dumps(extras, ensure_ascii=False))


def architecture_dot(service_names: set[str], edges: set[tuple[str, str]]) -> str:
    lines = [
        "digraph architecture {",
        "rankdir=LR;",
        'graph [bgcolor="transparent", pad="0.2"];',
        'node [shape=box, style="rounded,filled", fillcolor="#e8fbf7", color="#0f9b8e", fontname="Arial"];',
        'edge [color="#2d779f", penwidth=1.5];',
    ]
    for service in sorted(service_names):
        lines.append(f'"{dot_escape(service)}";')
    for source, target in sorted(edges):
        lines.append(f'"{dot_escape(source)}" -> "{dot_escape(target)}";')
    lines.append("}")
    return "\n".join(lines)


def render_trace(trace_path: Path | None, *, key: str) -> None:
    if trace_path is None or not trace_path.exists():
        st.info("Não há trace disponível para esta execução.")
        return
    events, warnings = read_jsonl_events(trace_path)
    st.caption(f"{len(events)} evento(s) JSON válido(s) em `{trace_path.name}`.")
    if warnings:
        for warning in warnings:
            st.warning(warning)
    show_sensitive = st.checkbox(
        "Mostrar prompts, respostas e saídas brutas do trace", key=f"sensitive_{key}", value=False
    )
    visible_events = events if show_sensitive else [strip_sensitive_event(event) for event in events]
    render_table(visible_events, key=f"events_{key}", download_name=trace_path.name, max_rows=1_000)
    render_file_download(
        trace_path,
        label="Baixar trace JSONL",
        mime="application/x-ndjson",
        key=f"trace_{key}",
        sensitive=True,
    )


def strip_sensitive_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value if key not in SENSITIVE_TRACE_FIELDS else "[oculto]"
        for key, value in event.items()
    }


def render_agent_trace_picker(paths: WorkspacePaths) -> None:
    st.markdown(
        '<p class="direct-prompt-label">Diretório de saída dos traces (dentro de outputs/)</p>',
        unsafe_allow_html=True,
    )
    output_directory_text = st.text_input(
        "Diretório de saída dos traces (dentro de outputs/)",
        value=active_outputs_value(),
        key="agent_trace_output_dir",
        label_visibility="collapsed",
    )
    try:
        outputs_dir = resolve_managed_path(paths.root, output_directory_text, paths.outputs_dir)
        records, _ = run_records(outputs_dir)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Não foi possível carregar resultados: {exc}")
        return
    agent_runs = [record for record in records if record.get("approach") == "agent" and record.get("trace_exists")]
    if not agent_runs:
        st.info("Ainda não há trace de uma execução por agente. Execute a estratégia agent e volte a esta aba.")
        return
    labels = [run_label(record) for record in agent_runs]
    st.markdown('<p class="direct-prompt-label">Execução por agente</p>', unsafe_allow_html=True)
    index = st.selectbox(
        "Execução por agente",
        range(len(agent_runs)),
        format_func=lambda item: labels[item],
        label_visibility="collapsed",
    )
    trace_path = Path(agent_runs[index]["trace_path"])
    render_trace(trace_path, key=f"agent_flow_{labels[index]}")


def render_comparison(paths: WorkspacePaths, config, projects) -> None:
    page_header(
        "Comparação entre prompt direto e agente",
        "Calcula métricas descritivas a partir dos CSVs finais e traces, sem chamar um LLM.",
    )
    controls = st.columns(3)
    controls[0].markdown(
        '<p class="direct-prompt-label">Diretório de outputs (dentro de outputs/)</p>',
        unsafe_allow_html=True,
    )
    output_text = controls[0].text_input(
        "Diretório de outputs (dentro de outputs/)",
        value=active_outputs_value(),
        key="comparison_outputs_source",
        label_visibility="collapsed",
    )
    controls[1].markdown(
        '<p class="direct-prompt-label">Diretório dos relatórios (dentro de comparison_outputs/)</p>',
        unsafe_allow_html=True,
    )
    comparison_text = controls[1].text_input(
        "Diretório dos relatórios (dentro de comparison_outputs/)",
        value="comparison_outputs",
        key="comparison_output_dir",
        label_visibility="collapsed",
    )
    controls[2].markdown(
        '<p class="direct-prompt-label">Mínimo de palavras na responsabilidade</p>',
        unsafe_allow_html=True,
    )
    min_words = int(
        controls[2].number_input(
            "Mínimo de palavras na responsabilidade",
            min_value=1,
            value=5,
            label_visibility="collapsed",
        )
    )
    try:
        outputs_dir = resolve_managed_path(paths.root, output_text, paths.outputs_dir)
        comparison_dir = resolve_managed_path(paths.root, comparison_text, paths.comparison_dir)
        artifact_problems = validate_output_artifacts(outputs_dir)
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Não foi possível validar os outputs: {exc}")
        return

    project_names = [project.name for project in projects]
    provider_names = [name for name, provider in config.providers.items() if provider.enabled]
    model_names = [
        model.name
        for provider in config.providers.values()
        if provider.enabled
        for model in provider.models
    ]
    filters = st.columns(5)
    filters[0].markdown('<p class="direct-prompt-label">Projeto</p>', unsafe_allow_html=True)
    project_filter = filters[0].selectbox(
        "Projeto", ["Todos", *project_names], key="comparison_project", label_visibility="collapsed"
    )
    filters[1].markdown('<p class="direct-prompt-label">Provedor</p>', unsafe_allow_html=True)
    provider_filter = filters[1].selectbox(
        "Provedor", ["Todos", *provider_names], key="comparison_provider", label_visibility="collapsed"
    )
    filters[2].markdown('<p class="direct-prompt-label">Modelo</p>', unsafe_allow_html=True)
    model_filter = filters[2].selectbox(
        "Modelo", ["Todos", *model_names], key="comparison_model", label_visibility="collapsed"
    )
    filters[3].markdown('<p class="direct-prompt-label">Template</p>', unsafe_allow_html=True)
    template_filter = filters[3].selectbox(
        "Template",
        ["Todos", *config.experiment.prompt_templates],
        key="comparison_template",
        label_visibility="collapsed",
    )
    filters[4].markdown('<p class="direct-prompt-label">Run (ex.: run_1)</p>', unsafe_allow_html=True)
    run_filter = filters[4].text_input(
        "Run (ex.: run_1)", key="comparison_run", label_visibility="collapsed"
    )

    if artifact_problems:
        st.error(
            "A comparação foi bloqueada porque metadata aponta para artefatos fora do diretório de outputs selecionado."
        )
        render_table(
            [{"problema": problem} for problem in artifact_problems],
            key="unsafe_comparison_artifacts",
            title="Caminhos bloqueados",
        )

    if st.button(
        "Calcular ou atualizar relatórios",
        type="primary",
        width="stretch",
        disabled=bool(artifact_problems),
    ):
        try:
            with st.spinner("Lendo outputs e calculando métricas..."):
                with exclusive_job_lock(paths.root, name="workbench"):
                    result = run_comparison(
                        outputs_dir=outputs_dir,
                        comparison_dir=comparison_dir,
                        project_name=none_if_all(project_filter),
                        provider=none_if_all(provider_filter),
                        model_name=none_if_all(model_filter),
                        prompt_template=none_if_all(template_filter),
                        run_id=run_filter.strip() or None,
                        min_responsibility_words=min_words,
                    )
                    write_comparison_manifest(
                        comparison_dir,
                        {
                            "outputs_directory": relative_workspace_path(paths, outputs_dir),
                            "comparison_directory": relative_workspace_path(paths, comparison_dir),
                            "filters": {
                                "project": none_if_all(project_filter),
                                "provider": none_if_all(provider_filter),
                                "model": none_if_all(model_filter),
                                "template": none_if_all(template_filter),
                                "run": run_filter.strip() or None,
                                "minimum_responsibility_words": min_words,
                            },
                            "result": {
                                "discovered_run_count": result.discovered_run_count,
                                "architecture_run_count": result.architecture_run_count,
                                "paired_run_count": result.paired_run_count,
                                "issue_count": result.issue_count,
                            },
                        },
                    )
            metrics = st.columns(4)
            for column, label, value in zip(
                metrics,
                (
                    "Execuções descobertas",
                    "Arquiteturas válidas",
                    "Pares válidos",
                    "Problemas registrados",
                ),
                (
                    result.discovered_run_count,
                    result.architecture_run_count,
                    result.paired_run_count,
                    result.issue_count,
                ),
                strict=True,
            ):
                column.markdown(
                    (
                        '<div class="direct-prompt-metric">'
                        f'<div class="direct-prompt-metric__label">{escape(label)}</div>'
                        f'<div class="direct-prompt-metric__value">{value}</div>'
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
            st.success(f"Relatórios atualizados em `{result.comparison_dir.as_posix()}`.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Não foi possível calcular a comparação: {exc}")

    try:
        reports = comparison_report_paths(comparison_dir, paths.root)
    except ValueError as exc:
        st.error(str(exc))
        return
    if not reports:
        st.info("Ainda não há relatórios. Execute a comparação depois que houver resultados em `outputs/`.")
        return
    manifest = read_comparison_manifest(comparison_dir)
    if manifest:
        generated_at = manifest.get("generated_at_utc", "")
        outputs_name = manifest.get("outputs_directory", "")
        st.caption(
            f"Estes relatórios foram atualizados pela interface em `{generated_at}` "
            f"a partir de `{outputs_name}`."
        )
        with st.expander("Filtros usados na última atualização"):
            st.json(manifest.get("filters", {}))
    report_names = [report.name for report in reports]
    st.markdown('<p class="direct-prompt-label">Relatório</p>', unsafe_allow_html=True)
    selected_name = st.selectbox(
        "Relatório", report_names, key="selected_comparison_report", label_visibility="collapsed"
    )
    report_path = next(report for report in reports if report.name == selected_name)
    rows = read_csv_rows(report_path)
    st.subheader(selected_name)
    if selected_name == "pairing_report.csv" and rows:
        pairing_frame = dataframe_from(rows)
        if "pair_status" in pairing_frame:
            st.bar_chart(pairing_frame["pair_status"].value_counts())
    render_table(rows, key=f"comparison_report_{selected_name}", download_name=selected_name, max_rows=2_000)
    render_file_download(
        report_path,
        label="Baixar arquivo original",
        mime="text/csv",
        key=f"comparison_{selected_name}",
    )
    st.caption(
        "Consulte a página “Configuração e documentação” para as fórmulas, status de pareamento e limitações de cada métrica."
    )


def none_if_all(value: str) -> str | None:
    return None if value == "Todos" else value


def render_documentation(paths: WorkspacePaths, config) -> None:
    page_header(
        "Configuração e documentação",
        "Referência rápida para modelos, caminhos de artefatos, comandos e métricas calculadas pelo repositório.",
    )
    tabs = st.tabs(["Configuração", "Como executar", "Métricas de comparação"])
    with tabs[0]:
        st.subheader("Provedores e modelos")
        provider_frame = dataframe_from(provider_rows(config))
        if not provider_frame.empty:
            st.dataframe(provider_frame, width="stretch", hide_index=True)
        experiment = config.experiment
        st.json(
            {
                "prompt_templates": experiment.prompt_templates,
                "default_runs": experiment.default_runs,
                "max_attempts": experiment.max_attempts,
                "agent.max_refinement_rounds": experiment.agent.max_refinement_rounds,
                "prompt_limits": experiment.prompt_limits.model_dump(),
                "paths": {
                    "systems": paths.systems_dir.as_posix(),
                    "static_analysis": paths.static_analysis_dir.as_posix(),
                    "outputs": paths.outputs_dir.as_posix(),
                    "comparison_outputs": paths.comparison_dir.as_posix(),
                },
            }
        )
    with tabs[1]:
        st.subheader("Início da interface")
        st.code(
            "python -m pip install -r requirements.txt\npython -m streamlit run src/ui/app.py",
            language="powershell",
        )
        st.subheader("Equivalente CLI: ambas as estratégias")
        st.code(
            "python -m src.main --project pet-clinic --provider deepseek --model deepseek-chat "
            "--approach direct --approach agent --prompt-template zero_shot "
            "--prompt-template few_shot --runs 1 --save-prompts",
            language="powershell",
        )
        st.info(
            "A interface executa comandos equivalentes após confirmação explícita. Use o modo seco primeiro para validar projeto, prompt e configuração sem custo de API."
        )
    with tabs[2]:
        readme_path = paths.root / "src" / "comparison" / "README.md"
        if not readme_path.exists():
            st.warning("O README da comparação não foi encontrado.")
            return
        documentation, truncated = read_limited_text(readme_path, max_chars=80_000)
        if truncated:
            st.warning("A documentação foi truncada na visualização; abra o arquivo para o conteúdo completo.")
        st.markdown(documentation)


if __name__ == "__main__":
    main()
