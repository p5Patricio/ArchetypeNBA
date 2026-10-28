import datetime
import math
import os
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from xhtml2pdf import pisa

radar_stats_categories: Dict[str, List[str]] = {
    "Ofensivas Clave": ["PTS", "AST", "FGM", "FGA", "TOV"],
    "Rebotes": ["REB", "OREB", "DREB"],
    "Tiro": ["FG_PCT", "FG3_PCT", "FT_PCT"],
    "Defensivas": ["STL", "BLK", "PF"],
}

STAT_NAMES_MAP: Dict[str, str] = {
    "MIN": "Minutos",
    "FGM": "Tiros de Campo Anotados",
    "FGA": "Tiros de Campo Intentados",
    "FG_PCT": "Tiros de Campo %",
    "FG3M": "Triples Anotados",
    "FG3A": "Triples Intentados",
    "FG3_PCT": "Triples %",
    "FTM": "Tiros Libres Anotados",
    "FTA": "Tiros Libres Intentados",
    "FT_PCT": "Tiros Libres %",
    "OREB": "Rebotes Ofensivos",
    "DREB": "Rebotes Defensivos",
    "REB": "Rebotes Totales",
    "AST": "Asistencias",
    "STL": "Robos",
    "BLK": "Bloqueos",
    "TOV": "Pérdidas de Balón",
    "PF": "Faltas Personales",
    "PTS": "Puntos",
    "GP": "Partidos Jugados",
    "GS": "Partidos Iniciados",
}


def assign_cluster_roles(cluster_means: pd.DataFrame) -> Dict[Any, str]:
    cluster_roles: Dict[Any, str] = {}
    for cluster_id, stats in cluster_means.iterrows():
        role = "Indefinido"
        stats = stats.fillna(0)
        if stats["MIN"] < 200 and stats["GP"] < 25 and stats["PTS"] < 100:
            role = "Jugador de Límite de Roster / Desarrollo"
        elif stats["BLK"] > 70 and stats["REB"] > 300 and stats["MIN"] > 800:
            role = "Protector de Aro / Pívot Defensivo"
        elif stats["FG_PCT"] > 0.60 and stats["REB"] > 400 and stats["PTS"] > 300:
            role = "Centro Dominante / Interior Eficiente"
        elif stats["REB"] > 350 and stats["MIN"] > 800 and stats["PTS"] < 600:
            role = "Hombre Grande Rebotador / De Rol"
        elif stats["AST"] > 350 and stats["MIN"] > 1200:
            if stats["PTS"] > 800 and stats["FG3M"] > 80:
                role = "Base Creador de Juego / Anotador"
            else:
                role = "Base Creador de Juego Puro"
        elif stats["AST"] > 150 and stats["MIN"] > 500 and stats["PTS"] < 500:
            if stats["FG3M"] > 70 and stats["FG3_PCT"] > 0.35:
                role = "Base de Rol / Facilitador (Tirador)"
            else:
                role = "Base de Rol / Manejador de Balón"
        elif stats["FG3_PCT"] > 0.38 and stats["FG3M"] > 150 and stats["FGA"] > 600:
            role = "Especialista en Triples / Escolta Anotador"
        elif stats["PTS"] > 800 and stats["FGA"] > 650:
            role = "Anotador de Volumen / Alero Ofensivo"
        elif (stats["STL"] > 80 or stats["BLK"] > 40) and stats["MIN"] > 700:
            role = "Defensor de Rol"
        elif (
            stats["PTS"] > 500
            and stats["AST"] > 150
            and stats["REB"] > 250
            and stats["MIN"] > 1000
            and stats["FG_PCT"] > 0.45
        ):
            role = "Jugador Completo (All-Around)"
        if role == "Indefinido":
            role = "Jugador de Rol General"
        cluster_roles[cluster_id] = role
    return cluster_roles


def create_radar_chart_to_file(
    ax,
    player_name: str,
    stats_to_plot: pd.Series,
    cluster_avg_stats: pd.Series,
    projected_stats: pd.Series,
    stats_labels: List[str],
    player_cluster_role: str,
    title: str = "Rendimiento del Jugador",
) -> None:
    num_vars = len(stats_labels)
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    angles += angles[:1]

    player_values = stats_to_plot.values.flatten().tolist()
    player_values += player_values[:1]

    cluster_avg_values = cluster_avg_stats.values.flatten().tolist()
    cluster_avg_values += cluster_avg_values[:1]

    projected_values = projected_stats.values.flatten().tolist()
    projected_values += projected_values[:1]

    color_player = "#22d3ee"  # cian
    color_cluster = "#a855f7"  # morado
    color_proj = "#3b82f6"  # azul

    ax.plot(angles, player_values, color=color_player, linewidth=2.5, label=f"{player_name} (Actual)")
    ax.fill(angles, player_values, color=color_player, alpha=0.20)

    cluster_label = f"Promedio {player_cluster_role} ({cluster_avg_stats.name})" if hasattr(cluster_avg_stats, "name") and cluster_avg_stats.name is not None else f"Promedio {player_cluster_role}"
    ax.plot(angles, cluster_avg_values, color=color_cluster, linewidth=2, label=cluster_label)
    ax.fill(angles, cluster_avg_values, color=color_cluster, alpha=0.12)

    ax.plot(angles, projected_values, color=color_proj, linewidth=2, linestyle="--", label=f"{player_name} (Proyectado)")
    ax.fill(angles, projected_values, color=color_proj, alpha=0.10)

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_rlabel_position(0)

    all_values = player_values + cluster_avg_values + projected_values
    max_val_plot = np.nanmax([v for v in all_values if np.isfinite(v) and not math.isnan(v)])
    max_val_plot = max_val_plot if max_val_plot > 0 else 1.0

    ax.set_ylim(0, max_val_plot * 1.25)
    ax.set_xticks(angles[:-1])
    display_stats_labels = [STAT_NAMES_MAP.get(s, s) for s in stats_labels]
    ax.set_xticklabels(display_stats_labels, fontsize=10)
    ax.set_title(title, va="bottom", fontsize=12, pad=30)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.3), fontsize=9)


def generate_player_report_pdf(
    player_name: str,
    player_row: pd.DataFrame,
    player_cluster: Any,
    cluster_roles: Dict[Any, str],
    player_stats_raw: pd.Series,
    cluster_avg_stats_raw: pd.Series,
    projected_stats_raw: pd.Series,
    comparison_df: pd.DataFrame,
    weak_areas_list: List[str],
    detailed_drills_html: str,
    all_stats_columns: List[str],
    radar_categories: Dict[str, List[str]],
) -> None:
    player_cluster_role = cluster_roles.get(player_cluster, "Rol Desconocido")
    img_filenames: List[str] = []

    all_radar_stats_for_pdf = [
        s for s in all_stats_columns
        if s not in ["PLAYER_ID", "SEASON_ID", "LEAGUE_ID", "TEAM_ID", "PLAYER_AGE"]
    ]
    player_stats_all_pdf = player_stats_raw[all_radar_stats_for_pdf].fillna(0)
    cluster_avg_stats_all_pdf = cluster_avg_stats_raw[all_radar_stats_for_pdf].fillna(0)
    projected_stats_all_pdf = projected_stats_raw[all_radar_stats_for_pdf].fillna(0)

    max_val_all_pdf = max(
        player_stats_all_pdf.max(),
        cluster_avg_stats_all_pdf.max(),
        projected_stats_all_pdf.max(),
    )
    max_val_all_pdf = max_val_all_pdf if max_val_all_pdf > 0 else 1

    normalized_player_stats_all_pdf = player_stats_all_pdf / max_val_all_pdf
    normalized_cluster_avg_stats_all_pdf = cluster_avg_stats_all_pdf / max_val_all_pdf
    normalized_projected_stats_all_pdf = projected_stats_all_pdf / max_val_all_pdf

    fig_global, ax_global = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    create_radar_chart_to_file(
        ax_global,
        player_name,
        normalized_player_stats_all_pdf,
        normalized_cluster_avg_stats_all_pdf,
        normalized_projected_stats_all_pdf,
        all_radar_stats_for_pdf,
        player_cluster_role,
        title=f"Rendimiento Global de {player_name} vs. Clúster y Proyección",
    )
    fig_global.tight_layout(pad=3.0)

    global_radar_img = f"radar_global_{player_name.replace(' ', '_')}.png"
    fig_global.savefig(global_radar_img, bbox_inches="tight", dpi=150)
    plt.close(fig_global)
    img_filenames.append(global_radar_img)

    for category_name, stats_list in radar_categories.items():
        current_stats_to_plot_pdf = [s for s in stats_list if s in all_stats_columns]
        if not current_stats_to_plot_pdf:
            continue

        player_stats_cat_pdf = player_stats_raw[current_stats_to_plot_pdf].fillna(0)
        cluster_avg_stats_cat_pdf = cluster_avg_stats_raw[current_stats_to_plot_pdf].fillna(0)
        projected_stats_cat_pdf = projected_stats_raw[current_stats_to_plot_pdf].fillna(0)

        max_for_category_pdf = max(
            player_stats_cat_pdf.max(),
            cluster_avg_stats_cat_pdf.max(),
            projected_stats_cat_pdf.max(),
        )
        max_for_category_pdf = max_for_category_pdf if max_for_category_pdf > 0 else 1

        normalized_player_stats_pdf = player_stats_cat_pdf / max_for_category_pdf
        normalized_cluster_avg_stats_pdf = cluster_avg_stats_cat_pdf / max_for_category_pdf
        normalized_projected_stats_pdf = projected_stats_cat_pdf / max_for_category_pdf

        fig_cat, ax_cat = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        create_radar_chart_to_file(
            ax_cat,
            player_name,
            normalized_player_stats_pdf,
            normalized_cluster_avg_stats_pdf,
            normalized_projected_stats_pdf,
            current_stats_to_plot_pdf,
            player_cluster_role,
            title=f"Rendimiento de {player_name} - {category_name}",
        )
        fig_cat.tight_layout(pad=3.0)

        cat_radar_img = f"radar_{category_name.replace(' ', '_')}_{player_name.replace(' ', '_')}.png"
        fig_cat.savefig(cat_radar_img, bbox_inches="tight", dpi=120)
        plt.close(fig_cat)
        img_filenames.append(cat_radar_img)

    season_val = player_row["SEASON_ID"].iloc[0] if "SEASON_ID" in player_row.columns and len(player_row) > 0 else ""
    team_val = player_row["TEAM_ABBREVIATION"].iloc[0] if "TEAM_ABBREVIATION" in player_row.columns and len(player_row) > 0 else ""
    age_val = float(player_row["PLAYER_AGE"].iloc[0]) if "PLAYER_AGE" in player_row.columns and len(player_row) > 0 else 25.0

    report_html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Reporte de Análisis de Jugador NBA: {player_name}</title>
        <style>
            body {{ font-family: 'Arial', sans-serif; margin: 20px; color: #333; }}
            h1, h2, h3 {{ color: #2C3E50; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .player-info, .cluster-info {{ margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 8px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .comparison-table td:nth-child(even) {{ background-color: #f9f9f9; }}
            .weak-areas ul {{ list-style-type: none; padding: 0; }}
            .weak-areas li {{ background-color: #ffe6e6; border-left: 5px solid #ff4d4d; margin-bottom: 8px; padding: 10px; border-radius: 4px; }}
            .drills-section ul {{ list-style-type: disc; margin-left: 20px; }}
            .drills-section li {{ margin-bottom: 5px; }}
            .chart-container {{ text-align: center; margin-bottom: 30px; }}
            .chart-container img {{ max-width: 90%; height: auto; border: 1px solid #ccc; border-radius: 5px; }}
            .footer {{ text-align: center; font-size: 0.8em; color: #777; margin-top: 30px; }}
            .good-performance {{ color: green; font-weight: bold; }}
            .weak-spot {{ color: red; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Reporte de Análisis de Jugador NBA</h1>
            <h2>{player_name}</h2>
            <p><strong>Temporada:</strong> {season_val} | 
                <strong>Equipo:</strong> {team_val} | 
                <strong>Edad:</strong> {age_val:.0f} años</p>
        </div>

        <div class="cluster-info">
            <h3>Información del Clúster</h3>
            <p>Este jugador ha sido agrupado en el <strong>Clúster {player_cluster} ({player_cluster_role})</strong>.</p>
            <p>Los jugadores de este clúster comparten perfiles estadísticos similares. El análisis compara el rendimiento de {player_name} con el promedio de jugadores de su mismo clúster.</p>
            <h4>Estadísticas Promedio del Clúster:</h4>
            <table class="comparison-table">
                <thead>
                    <tr>
                        <th>Estadística</th>
                        <th>Promedio Clúster</th>
                    </tr>
                </thead>
                <tbody>
    """
    for stat in [s for s in all_stats_columns if s in cluster_avg_stats_raw.index]:
        display_stat_name = STAT_NAMES_MAP.get(stat, stat)
        report_html += f"<tr><td>{display_stat_name}</td><td>{cluster_avg_stats_raw[stat]:.2f}</td></tr>"
    report_html += """
                </tbody>
            </table>
        </div>

        <div class="player-info">
            <h3>Comparación de Estadísticas</h3>
            <p>A continuación, se muestra la comparación de las estadísticas de {player_name} con el promedio de su clúster, incluyendo la diferencia y el porcentaje de diferencia.</p>
            <table class="comparison-table">
                <thead>
                    <tr>
                        <th>Estadística</th>
                        <th>Estadísticas del Jugador</th>
                        <th>Promedio Clúster</th>
                        <th>Diferencia</th>
                        <th>% Diferencia</th>
                    </tr>
                </thead>
                <tbody>
    """.format(player_name=player_name)

    for index, row in comparison_df.iterrows():
        player_val = row["Player Stats"]
        cluster_val = row["Cluster Average"]
        diff_val = row["Difference"]
        raw_percent_diff = row["Percentage Difference"]
        if isinstance(raw_percent_diff, str):
            percent_diff_val = float(raw_percent_diff.replace("%", ""))
        else:
            percent_diff_val = float(raw_percent_diff)
        percent_diff_str = f"{percent_diff_val:.2f}%"
        color_class = ""
        if percent_diff_val > 5:
            color_class = "good-performance"
        elif percent_diff_val < -5:
            color_class = "weak-spot"
        display_stat_name = STAT_NAMES_MAP.get(str(index), str(index))
        report_html += f"""
                    <tr>
                        <td>{display_stat_name}</td>
                        <td>{player_val:.2f}</td>
                        <td>{cluster_val:.2f}</td>
                        <td>{diff_val:.2f}</td>
                        <td class="{color_class}">{percent_diff_str}</td>
                    </tr>
        """
    report_html += """
                </tbody>
            </table>
        </div>

        <div class="weak-areas">
            <h3>Áreas Potencialmente Débiles Identificadas</h3>
            <ul>
    """
    if weak_areas_list:
        for area in weak_areas_list:
            report_html += f"<li>{area}</li>"
    else:
        report_html += "<li>No se identificaron áreas de debilidad significativas en comparación con el promedio de su clúster.</li>"
    report_html += f"""
            </ul>
        </div>
        
        <div class="chart-container">
            <h3>Gráficos de Rendimiento (Actual vs. Clúster vs. Proyección)</h3>
            <img src="{global_radar_img}" alt="Rendimiento Global">
            <p>Este gráfico muestra el perfil de rendimiento global de {player_name} en comparación con el promedio de su clúster y una proyección de mejora después del entrenamiento.</p>
        </div>
    """

    for category_name, stats_list in radar_categories.items():
        cat_radar_img = f"radar_{category_name.replace(' ', '_')}_{player_name.replace(' ', '_')}.png"
        if os.path.exists(cat_radar_img):
            report_html += f"""
            <div class="chart-container">
                <h4>Gráfico de Rendimiento: {category_name}</h4>
                <img src="{cat_radar_img}" alt="Rendimiento {category_name}">
                <p>Análisis detallado de las estadísticas {category_name.lower()} de {player_name}.</p>
            </div>
            """

    report_html += f"""
        <div class="drills-section">
            {detailed_drills_html}
        </div>

        <div class="footer">
            <p>Reporte generado por NBA Player Analyzer - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </body>
    </html>
    """

    output_filename = f"Reporte_{player_name.replace(' ', '_')}.pdf"

    try:
        with open(output_filename, "wb") as f:
            pisa_status = pisa.CreatePDF(
                report_html,
                dest=f,
                encoding="utf-8",
                link_callback=lambda uri, rel: os.path.join(os.getcwd(), uri),
            )
        if pisa_status.err:
            print(f"¡Error al generar PDF con xhtml2pdf para {player_name}!")
            print(pisa_status.err)
        else:
            print(f"Reporte PDF generado y guardado como: {output_filename}")
    except Exception as e:
        print(f"Error inesperado al generar PDF: {e}")

    for img_file in img_filenames:
        if os.path.exists(img_file):
            try:
                os.remove(img_file)
            except OSError:
                pass
