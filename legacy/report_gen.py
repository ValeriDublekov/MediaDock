import os
import json
import logging
from datetime import datetime
from rutracker_parser import iter_feed_definitions

logger = logging.getLogger(__name__)

def generate(db, config):
    """Генерира HTML отчет"""
    try:
        update_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        sorted_dates = sorted(db.keys(), reverse=True)
        f_cfg = config.get('filters', {})

        rss_html = ""
        for feed_def in iter_feed_definitions(config.get('rss_feeds', {})):
            rss_html += (
                f'<div class="rss-item"><span>{feed_def["name"]}</span>'
                f'<span class="copy-btn" onclick="copyRSS(\'{feed_def["url"]}\')">Copy Link</span></div>'
            )

        countries = set()
        for date in db:
            for item in db[date]:
                c_str = item.get('Country', 'N/A').split(',')[0].strip()
                if c_str and c_str != 'N/A':
                    countries.add(c_str)
        
        country_btns = ""
        for c in sorted(list(countries)):
            country_btns += f'<button class="toggle-btn" data-filter="country" data-val="{c}" onclick="toggleFilter(this)">{c}</button> '

        blank_img = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

        grid_html = ""
        
        # Дефиниции за типовете и техните хедъри
        type_order = ['Movie', 'TV Series', 'Documentary', 'Short']
        type_icons = {
            'Movie': '🎬',
            'TV Series': '📺',
            'Documentary': '🎥',
            'Short': '🎞️'
        }
        
        for date in sorted_dates:
            if not db[date]: continue
            f_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
            grid_html += f"<h2 class='date-section'>{f_date}</h2>"
            
            # Групиране по тип
            items_by_type = {}
            for m in db[date]:
                p_type = m.get('DisplayType', 'Movie')
                if p_type not in items_by_type:
                    items_by_type[p_type] = []
                items_by_type[p_type].append(m)
            
            # Рендериране по типове в определен ред
            for p_type in type_order:
                if p_type not in items_by_type:
                    continue
                
                items = items_by_type[p_type]
                icon = type_icons.get(p_type, '🎬')
                count = len(items)
                
                grid_html += f"<h3 class='type-section'>{icon} {p_type}s <span class='count'>({count})</span></h3>"
                grid_html += "<div class='grid'>"
                
                for m in items:
                    title = m.get('Title', 'Unknown')
                    country = m.get('Country', 'N/A')
                    rating = m.get('imdbRating', 'N/A')
                    votes = str(m.get('imdbVotes', '0')).replace(',', '')
                    if votes == "N/A": votes = "0"
                    
                    type_class = f"type-{p_type.lower().split()[0]}"
                    rt = next((r['Value'] for r in m.get('Ratings', []) if r['Source'] == 'Rotten Tomatoes'), 'N/A')
                    mc = next((r['Value'] for r in m.get('Ratings', []) if r['Source'] == 'Metacritic'), 'N/A')

                    grid_html += f"""
                    <div class="card" data-type="{p_type}" data-country="{country.split(',')[0].strip()}" 
                         data-rating="{rating}" data-votes="{votes}" 
                         data-search="{title} {m.get('Genre')} {m.get('Director')}">
                        <div class="main-rating">⭐ {rating}</div>
                        <div class="poster-container">
                            <img src="{m['Poster']}" onerror="this.src='data:image/png;base64,{blank_img}'">
                            <div class="overlay">
                                <div class="overlay-title">{title}</div>
                                <div class="overlay-plot">{m.get('Plot', 'No plot available.')[:160]}...</div>
                                <div class="stat-row"><span>Country:</span><span>{country}</span></div>
                                <div class="stat-row"><span>Director:</span><span>{m.get('Director', 'N/A')}</span></div>
                                <div class="stat-row"><span>Runtime:</span><span>{m.get('Runtime', 'N/A')}</span></div>
                                <div class="ratings-box" style="background:#222; padding:8px; border-radius:6px; margin-top:10px; border:1px solid #333;">
                                    <div class="stat-row" style="border:none"><span>⭐ IMDb:</span><span>{rating} ({m.get('imdbVotes','0')})</span></div>
                                    <div class="stat-row" style="border:none"><span>🍅 Rotten:</span><span>{rt}</span></div>
                                    <div class="stat-row" style="border:none"><span>Ⓜ️ Metacritic:</span><span>{mc}</span></div>
                                </div>
                                <div style="color:#f5c518; margin-top:auto; font-size:9px;">🏆 {m.get('Awards', '')}</div>
                            </div>
                            {f'<div class="quality-tag">{m["Quality"]}</div>' if m.get("Quality") else ''}
                        </div>
                        <div class="card-content">
                            <span class="type-badge {type_class}">{p_type}</span>
                            <span style="font-size:11px; color:#eee; font-weight:bold; display:block; margin-bottom:5px;">🌎 {country}</span>
                            <div class="title">{title} ({m.get('Year', 'N/A')})</div>
                            <div class="btn-group">
                                <a href="{m['Link']}" class="btn btn-rutracker" target="_blank">Torrent</a>
                                <a href="https://www.imdb.com/title/{m.get('imdbID', '')}" class="btn btn-imdb" target="_blank">IMDb</a>
                            </div>
                        </div>
                    </div>
                    """
                
                grid_html += "</div>"

        # Зареждане на темплейта
        template_path = os.path.join('templates', 'dashboard_template.html')
        if not os.path.exists(template_path):
            # Fallback към стария път
            template_path = 'dashboard_template.html'
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()

        replacements = {
            '{{UPDATE_TIME}}': update_time,
            '{{COUNTRY_BUTTONS}}': country_btns,
            '{{GRID_CONTENT}}': grid_html,
            '{{RSS_LIST}}': rss_html,
            '{{DEF_MOVIE_RATING}}': str(f_cfg.get('default_movie_rating', 6.8)),
            '{{DEF_SERIES_RATING}}': str(f_cfg.get('default_series_rating', 8.0)),
            '{{DEF_VOTES}}': str(f_cfg.get('default_min_votes', 500)),
            '{{DEF_SHOW_NEW}}': 'checked' if f_cfg.get('default_show_new', True) else '',
            '{{EXCLUDED_COUNTRIES}}': ", ".join(f_cfg.get('excluded_countries', [])),
            '{{EXCLUDED_GENRES}}': ", ".join(f_cfg.get('excluded_genres', [])),
            '{{API_KEY_HIDDEN}}': config.get('omdb_api_key', '')[:4] + "****",
            '{{DAYS_TO_KEEP}}': str(config.get('days_to_keep', 5))
        }

        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)

        # Запис на основния отчет
        output_path = os.path.join('output', 'index.html')
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(template)
        
        logger.info(f"✅ Report generated: {output_path}")
        
        # Запис на архивна копия ако е разрешено
        if config.get('archive_reports', True):
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            archive_path = os.path.join('output', 'reports', f'report_{timestamp}.html')
            with open(archive_path, "w", encoding="utf-8") as f:
                f.write(template)
            logger.info(f"📁 Archived: {archive_path}")
        
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        raise
