from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from scheduler import load_schedule


def get_calendar_events() -> list[dict[str, Any]]:
    records = load_schedule()
    events: list[dict[str, Any]] = []

    for item in records:
        sched_time = item.get("scheduled_for") or item.get("created_at") or ""
        date_str = ""
        time_str = ""
        if sched_time:
            try:
                dt = datetime.fromisoformat(str(sched_time).replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M")
            except Exception:
                date_str = str(sched_time)[:10]

        events.append(
            {
                "id": item.get("id") or "",
                "title": item.get("article_title") or "Gepland Bericht",
                "date": date_str,
                "time": time_str,
                "platform": item.get("platform") or "linkedin",
                "content_type": item.get("content_type") or "post",
                "status": item.get("status") or "queued",
                "teaser": item.get("article_teaser") or "",
                "notes": item.get("notes") or "",
                "edit_url": f"/editor?content={item.get('content_item_id')}"
                if item.get("content_item_id")
                else "/editor",
            }
        )

    # Also check real content items if available
    try:
        from content_store import list_content_items
        from dashboard import CONFIG_PATH, load_config

        cfg = load_config(CONFIG_PATH)
        content_items = list_content_items(cfg.content_dir)
        existing_ids = {e["id"] for e in events}

        for citem in content_items:
            if citem.id in existing_ids:
                continue
            date_val = citem.updated_at or citem.created_at or ""
            date_str = date_val[:10] if date_val else ""
            time_str = date_val[11:16] if len(date_val) >= 16 else ""

            events.append(
                {
                    "id": citem.id,
                    "title": citem.title or citem.slug or "Artikel Concept",
                    "date": date_str,
                    "time": time_str,
                    "platform": "website",
                    "content_type": "article",
                    "status": "draft",
                    "teaser": citem.markdown_body[:120] if citem.markdown_body else "",
                    "notes": "Website artikel concept",
                    "edit_url": f"/editor?content={citem.id}",
                }
            )
    except Exception:
        pass

    return events


def render_calendar_page() -> str:
    events = get_calendar_events()
    events_json = json.dumps(events, ensure_ascii=False)

    return f"""
    <section class="calendar-wrapper">
      <div class="calendar-header">
        <div class="calendar-title-group">
          <h2>Publicatie Kalender 📅</h2>
          <p class="subtitle">Overzicht van geplande artikelen, social posts en concepten per dag.</p>
        </div>
        <div class="calendar-controls">
          <div class="btn-group">
            <button type="button" id="cal-prev-btn" class="button secondary">‹ Vorige</button>
            <button type="button" id="cal-today-btn" class="button secondary">Vandaag</button>
            <button type="button" id="cal-next-btn" class="button secondary">Volgende ›</button>
          </div>
          <span id="cal-month-label" class="calendar-month-label">Augustus 2026</span>
          <div class="btn-group">
            <button type="button" id="view-month-btn" class="button active">Maand</button>
            <button type="button" id="view-week-btn" class="button secondary">Week</button>
            <button type="button" id="view-list-btn" class="button secondary">Lijst</button>
          </div>
        </div>
      </div>

      <!-- Month & Week Grid View -->
      <div id="calendar-grid-container" class="calendar-grid-container">
        <div class="calendar-weekdays">
          <div>Ma</div><div>Di</div><div>Wo</div><div>Do</div><div>Vr</div><div>Za</div><div>Zo</div>
        </div>
        <div id="calendar-days" class="calendar-days"></div>
      </div>

      <!-- List View Container (Hidden by default) -->
      <div id="calendar-list-container" class="calendar-list-container" style="display:none;">
        <div id="calendar-list-items" class="content-list"></div>
      </div>
    </section>

    <!-- Post Detail Modal -->
    <div id="event-modal" class="modal-backdrop" style="display:none;" onclick="if(event.target===this)closeEventModal()">
      <div class="modal-card">
        <div class="modal-header">
          <h3 id="modal-title">Bericht Details</h3>
          <button type="button" class="modal-close" onclick="closeEventModal()">×</button>
        </div>
        <div class="modal-body">
          <div class="facts" style="margin-bottom:16px;">
            <dt>Status</dt><dd id="modal-status"></dd>
            <dt>Kanaal</dt><dd id="modal-platform"></dd>
            <dt>Datum & Tijd</dt><dd id="modal-datetime"></dd>
            <dt>Type</dt><dd id="modal-type"></dd>
          </div>
          <div style="margin-bottom:16px;">
            <strong>Teaser Preview:</strong>
            <div id="modal-teaser" class="preview" style="margin-top:6px;max-height:160px;font-size:0.9rem;color:var(--text-muted);"></div>
          </div>
          <div id="modal-notes-container" style="margin-bottom:16px;display:none;">
            <strong>Notities:</strong>
            <p id="modal-notes" style="margin-top:4px;font-size:0.88rem;color:var(--text-muted);"></p>
          </div>
        </div>
        <div class="modal-footer actions">
          <a id="modal-edit-link" class="button" href="/editor">Open in Editor</a>
          <button type="button" class="button secondary" onclick="closeEventModal()">Sluiten</button>
        </div>
      </div>
    </div>

    <style>
      .calendar-wrapper {{ display: grid; gap: 20px; }}
      .calendar-header {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px; background: var(--surface); padding: 18px; border: 1px solid var(--line); border-radius: var(--radius); }}
      .calendar-title-group h2 {{ margin: 0; font-size: 22px; }}
      .calendar-title-group p {{ margin: 4px 0 0; font-size: 13px; color: var(--muted); }}
      .calendar-controls {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
      .calendar-month-label {{ font-size: 16px; font-weight: 700; color: var(--text); min-width: 140px; text-align: center; }}
      .btn-group {{ display: inline-flex; gap: 4px; background: rgba(9, 9, 11, 0.5); padding: 3px; border-radius: var(--radius); border: 1px solid var(--line); }}
      .btn-group .button {{ min-height: 32px; padding: 4px 10px; font-size: 12px; border: 0; border-radius: calc(var(--radius) - 2px); }}
      .btn-group .button.active {{ background: var(--accent); color: #fff; }}

      .calendar-grid-container {{ border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; background: var(--surface); }}
      .calendar-weekdays {{ display: grid; grid-template-columns: repeat(7, 1fr); background: rgba(9, 9, 11, 0.8); border-bottom: 1px solid var(--line); font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }}
      .calendar-weekdays > div {{ padding: 10px; text-align: center; border-right: 1px solid rgba(63, 63, 70, 0.4); }}
      .calendar-weekdays > div:last-child {{ border-right: 0; }}

      .calendar-days {{ display: grid; grid-template-columns: repeat(7, 1fr); auto-rows: minmax(120px, auto); background: var(--bg-soft); gap: 1px; }}
      .day-cell {{ background: var(--surface); padding: 8px; display: flex; flex-direction: column; gap: 6px; transition: background 0.15s ease; min-height: 120px; }}
      .day-cell.outside {{ background: rgba(18, 18, 20, 0.4); opacity: 0.45; }}
      .day-cell.today {{ background: rgba(63, 63, 70, 0.25); box-shadow: inset 0 0 0 1.5px var(--accent-strong); }}
      .day-header {{ display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 700; color: var(--muted); }}
      .day-cell.today .day-number {{ background: var(--text); color: var(--bg); width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; }}
      .event-chip {{ padding: 4px 6px; border-radius: 5px; font-size: 11.5px; font-weight: 600; cursor: pointer; border: 1px solid transparent; display: flex; flex-direction: column; gap: 2px; transition: transform 0.1s ease, filter 0.1s ease; overflow: hidden; }}
      .event-chip:hover {{ transform: translateY(-1px); filter: brightness(1.15); }}
      
      .event-chip.queued {{ background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.4); color: #93c5fd; }}
      .event-chip.done {{ background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.4); color: #a7f3d0; }}
      .event-chip.failed {{ background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.4); color: #fca5a5; }}
      .event-chip.draft {{ background: rgba(161, 161, 170, 0.15); border-color: rgba(161, 161, 170, 0.3); color: #d4d4d8; }}

      .chip-meta {{ display: flex; align-items: center; gap: 4px; font-size: 10px; opacity: 0.85; text-transform: uppercase; font-weight: 700; }}
      .chip-title {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 11.5px; }}

      /* Modal styling */
      .modal-backdrop {{ position: fixed; inset: 0; background: rgba(0, 0, 0, 0.75); backdrop-filter: blur(4px); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 16px; }}
      .modal-card {{ background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); width: 100%; max-width: 520px; padding: 20px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }}
      .modal-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--line); padding-bottom: 10px; }}
      .modal-header h3 {{ margin: 0; font-size: 18px; }}
      .modal-close {{ background: none; border: 0; color: var(--muted); font-size: 24px; cursor: pointer; padding: 0; line-height: 1; }}
      .modal-close:hover {{ color: var(--text); }}
      .modal-footer {{ display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; border-top: 1px solid var(--line); padding-top: 14px; }}

      @media (max-width: 768px) {{
        .calendar-weekdays > div {{ font-size: 10px; padding: 6px 2px; }}
        .day-cell {{ min-height: 90px; padding: 4px; }}
        .chip-title {{ font-size: 10px; }}
      }}
    </style>

    <script>
      const rawEvents = {events_json};
      let currentDate = new Date();
      let currentView = 'month';

      const monthNames = [
        'Januari', 'Februari', 'Maart', 'April', 'Mei', 'Juni',
        'Juli', 'Augustus', 'September', 'Oktober', 'November', 'December'
      ];

      const platformIcons = {{
        linkedin: '💼 LinkedIn',
        youtube: '📺 YouTube',
        x: '🐤 X (Twitter)',
        substack: '📰 Substack',
        instagram: '📸 Instagram',
        website: '🌐 Website'
      }};

      function initCalendar() {{
        renderCalendar();

        document.getElementById('cal-prev-btn')?.addEventListener('click', () => {{
          if (currentView === 'month') currentDate.setMonth(currentDate.getMonth() - 1);
          else currentDate.setDate(currentDate.getDate() - 7);
          renderCalendar();
        }});

        document.getElementById('cal-next-btn')?.addEventListener('click', () => {{
          if (currentView === 'month') currentDate.setMonth(currentDate.getMonth() + 1);
          else currentDate.setDate(currentDate.getDate() + 7);
          renderCalendar();
        }});

        document.getElementById('cal-today-btn')?.addEventListener('click', () => {{
          currentDate = new Date();
          renderCalendar();
        }});

        document.getElementById('view-month-btn')?.addEventListener('click', (e) => setView('month', e.target));
        document.getElementById('view-week-btn')?.addEventListener('click', (e) => setView('week', e.target));
        document.getElementById('view-list-btn')?.addEventListener('click', (e) => setView('list', e.target));
      }}

      function setView(view, btn) {{
        currentView = view;
        document.querySelectorAll('.btn-group .button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const gridContainer = document.getElementById('calendar-grid-container');
        const listContainer = document.getElementById('calendar-list-container');

        if (view === 'list') {{
          gridContainer.style.display = 'none';
          listContainer.style.display = 'block';
          renderListView();
        }} else {{
          gridContainer.style.display = 'block';
          listContainer.style.display = 'none';
          renderCalendar();
        }}
      }}

      function renderCalendar() {{
        const label = document.getElementById('cal-month-label');
        if (label) label.textContent = `${{monthNames[currentDate.getMonth()]}} ${{currentDate.getFullYear()}}`;

        const daysContainer = document.getElementById('calendar-days');
        if (!daysContainer) return;
        daysContainer.innerHTML = '';

        const year = currentDate.getFullYear();
        const month = currentDate.getMonth();

        const today = new Date();
        const todayStr = `${{today.getFullYear()}}-${{String(today.getMonth() + 1).padStart(2, '0')}}-${{String(today.getDate()).padStart(2, '0')}}`;

        if (currentView === 'month') {{
          const firstDayIndex = (new Date(year, month, 1).getDay() + 6) % 7; // Mon = 0
          const totalDays = new Date(year, month + 1, 0).getDate();
          const prevMonthTotalDays = new Date(year, month, 0).getDate();

          // Previous month padding days
          for (let i = firstDayIndex - 1; i >= 0; i--) {{
            const dayNum = prevMonthTotalDays - i;
            const prevMonthDate = new Date(year, month - 1, dayNum);
            const dateStr = formatDateStr(prevMonthDate);
            daysContainer.appendChild(createDayCell(dayNum, dateStr, true, false));
          }}

          // Current month days
          for (let day = 1; day <= totalDays; day++) {{
            const thisDate = new Date(year, month, day);
            const dateStr = formatDateStr(thisDate);
            const isToday = dateStr === todayStr;
            daysContainer.appendChild(createDayCell(day, dateStr, false, isToday));
          }}

          // Next month padding days to complete 35 or 42 grid cells
          const currentCellCount = firstDayIndex + totalDays;
          const targetTotal = currentCellCount > 35 ? 42 : 35;
          for (let day = 1; day <= (targetTotal - currentCellCount); day++) {{
            const nextMonthDate = new Date(year, month + 1, day);
            const dateStr = formatDateStr(nextMonthDate);
            daysContainer.appendChild(createDayCell(day, dateStr, true, false));
          }}
        }} else if (currentView === 'week') {{
          // Week view calculation
          const curr = new Date(currentDate);
          const first = curr.getDate() - ((curr.getDay() + 6) % 7);
          for (let i = 0; i < 7; i++) {{
            const dayDate = new Date(curr.setDate(first + i));
            const dateStr = formatDateStr(dayDate);
            const isToday = dateStr === todayStr;
            daysContainer.appendChild(createDayCell(dayDate.getDate(), dateStr, false, isToday));
          }}
        }}
      }}

      function formatDateStr(d) {{
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${{y}}-${{m}}-${{day}}`;
      }}

      function createDayCell(dayNum, dateStr, isOutside, isToday) {{
        const cell = document.createElement('div');
        cell.className = `day-cell${{isOutside ? ' outside' : ''}}${{isToday ? ' today' : ''}}`;

        const header = document.createElement('div');
        header.className = 'day-header';
        header.innerHTML = `<span class="day-number">${{dayNum}}</span>`;
        cell.appendChild(header);

        // Filter events matching dateStr
        const dayEvents = rawEvents.filter(ev => ev.date === dateStr);
        dayEvents.forEach(ev => {{
          const chip = document.createElement('div');
          chip.className = `event-chip ${{ev.status || 'queued'}}`;
          const pIcon = platformIcons[ev.platform] || '💼 Social';
          chip.innerHTML = `
            <div class="chip-meta">
              <span>${{pIcon}}</span>
              ${{ev.time ? `<span>· ${{ev.time}}</span>` : ''}}
            </div>
            <div class="chip-title">${{escapeHtml(ev.title)}}</div>
          `;
          chip.addEventListener('click', () => openEventModal(ev));
          cell.appendChild(chip);
        }});

        return cell;
      }}

      function renderListView() {{
        const listItems = document.getElementById('calendar-list-items');
        if (!listItems) return;
        listItems.innerHTML = '';

        if (rawEvents.length === 0) {{
          listItems.innerHTML = '<article class="panel"><h2>Geen geplande berichten</h2><p>Er zijn nog geen geplande posts of concepten aanwezig.</p></article>';
          return;
        }}

        const sorted = [...rawEvents].sort((a, b) => (b.date + b.time).localeCompare(a.date + a.time));
        sorted.forEach(ev => {{
          const row = document.createElement('article');
          row.className = 'content-row';
          const pIcon = platformIcons[ev.platform] || '💼 Social';
          row.innerHTML = `
            <div>
              <h3>${{escapeHtml(ev.title)}}</h3>
              <p style="margin:4px 0 0;font-size:0.85rem;color:var(--text-muted);">
                <span class="status ${{ev.status === 'done' ? 'ok' : (ev.status === 'failed' ? 'bad' : 'info')}}">${{ev.status}}</span>
                · ${{pIcon}} · ${{ev.date}} ${{ev.time || ''}}
              </p>
            </div>
            <div class="actions">
              <button type="button" class="button secondary" onclick='openEventModal(${{JSON.stringify(ev)}})'>Details</button>
              <a class="button" href="${{ev.edit_url}}">Editor</a>
            </div>
          `;
          listItems.appendChild(row);
        }});
      }}

      function openEventModal(ev) {{
        document.getElementById('modal-title').textContent = ev.title || 'Gepland Bericht';
        document.getElementById('modal-status').innerHTML = `<span class="status ${{ev.status === 'done' ? 'ok' : (ev.status === 'failed' ? 'bad' : 'info')}}">${{ev.status || 'queued'}}</span>`;
        document.getElementById('modal-platform').textContent = platformIcons[ev.platform] || ev.platform;
        document.getElementById('modal-datetime').textContent = `${{ev.date || 'Onbekend'}} ${{ev.time ? 'om ' + ev.time : ''}}`;
        document.getElementById('modal-type').textContent = ev.content_type || 'post';

        document.getElementById('modal-teaser').textContent = ev.teaser || 'Geen preview beschikbaar.';

        const notesContainer = document.getElementById('modal-notes-container');
        if (ev.notes) {{
          document.getElementById('modal-notes').textContent = ev.notes;
          notesContainer.style.display = 'block';
        }} else {{
          notesContainer.style.display = 'none';
        }}

        const editLink = document.getElementById('modal-edit-link');
        if (editLink) editLink.href = ev.edit_url || '/editor';

        document.getElementById('event-modal').style.display = 'flex';
      }}

      function closeEventModal() {{
        document.getElementById('event-modal').style.display = 'none';
      }}

      function escapeHtml(str) {{
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }}

      document.addEventListener('DOMContentLoaded', initCalendar);
    </script>
    """
