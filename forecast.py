"""Unicorn low tide finder for the Half Moon Bay tide pools.

Tides are predictable years ahead, so this lists every upcoming "unicorn Saturday":
a Saturday afternoon low tide of -1.0 ft or lower (MLLW) that comes at noon or later
and at least 30 minutes before sunset, so there are 3+ hours of daylight on the
falling tide and light left at the bottom. -0.75 ft or lower on the same terms is an
"almost unicorn". These are mostly November-February afternoons.

Writes site/data.json for the web page and emails a reminder 7 days before and the
day before each qualifying Saturday. Standard library only.

Email alerts need these environment variables (GitHub Actions secrets):
  GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_EMAILS (comma-separated, sent in BCC).
Without them it prints the message instead of sending.
"""
import json, math, os, smtplib, time, urllib.request
from email.message import EmailMessage
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
PT = ZoneInfo('America/Los_Angeles')
LAT, LON = 37.4337, -122.4436      # Half Moon Bay tide pools
STATION = '9414131'                # NOAA Pillar Point Harbor, about 5 miles north
UNICORN_FT = -1.0
ALMOST_FT = -0.75
EARLIEST = 12                      # low tide at noon or later
SUNSET_BUFFER_MIN = 30             # low at least this long before sunset
YEARS_AHEAD = 4                    # rolling window: everything from today to 4 years from today
DRIVE_MIN = 60                     # San Francisco to the Ritz-Carlton parking
WALK_MIN = 20                      # Ritz-Carlton down to the beach
SUMMER_AFTER_SUNRISE_MIN = 0       # summer lows: any time after sunrise
SUMMER_COUNT = 4                   # lowest N daylight lows per summer
UA = {'User-Agent': '(unicorn-tides alert, personal project)'}
API = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(15 * (i + 1))


def predictions(begin, end, interval):
    url = (f'{API}?product=predictions&station={STATION}&begin_date={begin:%Y%m%d}&end_date={end:%Y%m%d}'
           f'&datum=MLLW&units=english&time_zone=lst_ldt&interval={interval}&format=json&application=unicorn_tides')
    return [(datetime.fromisoformat(p['t']).replace(tzinfo=PT), float(p['v']), p.get('type'))
            for p in get(url)['predictions']]


def sun(d):
    """Sunrise and sunset (NOAA's simple solar algorithm, within a couple of minutes)."""
    g = 2 * math.pi / 365 * (d.timetuple().tm_yday - 1)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(math.radians(LAT)) * math.cos(decl))
                                - math.tan(math.radians(LAT)) * math.tan(decl)))
    base = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    rise = base + timedelta(minutes=720 - 4 * (LON + ha) - eq)
    sset = base + timedelta(minutes=720 - 4 * (LON - ha) - eq)
    return rise.astimezone(PT), sset.astimezone(PT)


def clock(t):
    return t.strftime('%-I:%M %p').lower().replace(':00', '')


def hours(t):
    return round(t.hour + t.minute / 60, 2)


def horizon_for(today):
    """4 years from today, extended so the last season is complete:
    through Aug 31 if that date falls in Mar-Aug, else through the end of February."""
    base = date(today.year + YEARS_AHEAD, today.month, min(today.day, 28))
    if 3 <= base.month <= 8:
        return date(base.year, 8, 31)
    y = base.year + 1 if base.month >= 9 else base.year
    return date(y, 3, 1) - timedelta(days=1)


def add_travel(s, pts, not_before=None):
    """Be on the beach when the falling tide drops below 0 ft (interpolated between 6-minute points),
    or at not_before (sunrise) if that's later."""
    falling = [(t, v) for t, v, _ in pts if hours(t) <= s['low_h']]
    cross = falling[0][0]
    for (t0, v0), (t1, v1) in zip(falling, falling[1:]):
        if v0 >= 0 > v1:
            cross = t0 + (t1 - t0) * (v0 / (v0 - v1))
    if not_before and cross < not_before:
        cross = not_before
    cross = cross.replace(second=0, microsecond=0)
    s['below_zero'] = clock(cross)
    s['below_zero_h'] = hours(cross)
    s['at_ritz'] = clock(cross - timedelta(minutes=WALK_MIN))
    s['leave_sf'] = clock(cross - timedelta(minutes=DRIVE_MIN + WALK_MIN))


def summer_lows(today):
    """The lowest daylight tides of each summer (May-Aug) through YEARS_AHEAD, Saturdays only,
    at least SUMMER_AFTER_SUNRISE_MIN after sunrise. For seaweed foraging and poke poling."""
    out = []
    year = today.year if today < date(today.year, 8, 31) else today.year + 1
    horizon = horizon_for(today)
    for y in range(year, horizon.year + 1):
        if date(y, 5, 1) > horizon:
            break
        start = max(date(y, 5, 1), today)
        cands = []
        for t, v, kind in predictions(start, min(date(y, 8, 31), horizon), 'hilo'):
            rise, sset = sun(t.date())
            if kind == 'L' and v < 0 and t.weekday() == 5 and rise + timedelta(minutes=SUMMER_AFTER_SUNRISE_MIN) <= t <= sset:
                cands.append((v, t, rise))
        for v, t, rise in sorted(cands)[:SUMMER_COUNT]:
            s = dict(date=t.date().isoformat(), label=t.strftime('%a %b %-d, %Y'), summer=y,
                     low_ft=round(v, 2), low_time=clock(t), low_h=hours(t), sunrise=clock(rise),
                     days_away=(t.date() - today).days)
            pts = predictions(t.date(), t.date(), '6')
            s['sunrise_h'] = hours(rise)
            s['curve'] = [[hours(p), round(pv, 2)] for p, pv, _ in pts if 3 <= hours(p) <= 13 and p.minute % 30 == 0]
            add_travel(s, pts, not_before=rise)
            out.append(s)
    return sorted(out, key=lambda s: s['date'])


def build():
    now = datetime.now(PT)
    today = now.date()
    lows = []
    horizon = horizon_for(today)
    for y in range(today.year, horizon.year + 1):
        lows += [(t, v) for t, v, kind in predictions(date(y, 1, 1), date(y, 12, 31), 'hilo') if kind == 'L']

    saturdays, misses, minor = [], [], []
    for t, v in lows:
        if t.date() < today or t.date() > horizon or t.weekday() != 5 or v >= 0:
            continue
        rise, sset = sun(t.date())
        before_sunset = (sset - t).total_seconds() / 60
        ok = t.hour >= EARLIEST and before_sunset >= SUNSET_BUFFER_MIN
        tier = 'unicorn' if v <= UNICORN_FT else 'almost' if v <= ALMOST_FT else 'minor'
        info = dict(date=t.date().isoformat(), label=t.strftime('%a %b %-d, %Y'), tier=tier,
                    low_ft=round(v, 2), low_time=clock(t), low_h=hours(t),
                    sunrise=clock(rise), sunset=clock(sset), sunset_h=hours(sset),
                    minutes_before_sunset=round(before_sunset),
                    days_away=(t.date() - today).days)
        if ok and tier == 'minor':
            minor.append(info)
        elif ok:
            saturdays.append(info)
        elif tier == 'unicorn':
            info['why'] = ('after dark' if before_sunset < 0 else 'right at sunset' if t.hour >= EARLIEST
                           else 'before sunrise' if t < rise else 'a morning low, not afternoon')
            misses.append(info)

    # Afternoon tide curves for the next few qualifying Saturdays (noon to an hour after sunset)
    for s in saturdays:
        d = date.fromisoformat(s['date'])
        pts = predictions(d, d, '6')
        s['curve'] = [[hours(t), round(v, 2)] for t, v, _ in pts
                      if 11 <= hours(t) <= s['sunset_h'] + 1.5 and t.minute % 30 == 0]
        add_travel(s, pts)
    for s in minor:  # smaller afternoon minus tides (0 to -0.75 ft): just the Leave SF time
        d = date.fromisoformat(s['date'])
        add_travel(s, predictions(d, d, '6'))

    summer = summer_lows(today)
    return dict(
        generated=now.isoformat(), generated_local=now.strftime('%a %b %-d, %-I:%M %p'),
        horizon=horizon_for(today).strftime('%b %-d, %Y'),
        rule=dict(unicorn_ft=UNICORN_FT, almost_ft=ALMOST_FT, earliest=EARLIEST,
                  sunset_buffer_min=SUNSET_BUFFER_MIN, station=STATION),
        saturdays=saturdays, minor=minor, misses=[m for m in misses if m['date'] not in {x['date'] for x in summer}], summer=summer,
    )


# ---------- alerts ----------

def send_emails(subject, body):
    user, password = os.environ.get('GMAIL_USER'), os.environ.get('GMAIL_APP_PASSWORD')
    recipients = [e.strip() for e in os.environ.get('ALERT_EMAILS', '').split(',') if e.strip()]
    if not (user and password and recipients):
        print('[dry run, no Gmail settings] would email:', subject, '|', body)
        return False
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, f'Unicorn Low Tide <{user}>', user
    msg['Bcc'] = ', '.join(recipients)
    msg.set_content(body)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    print(f'emailed {len(recipients)} address(es)')
    return True


def main():
    data = build()
    (ROOT / 'site' / 'data.json').write_text(json.dumps(data, indent=1))
    state_path = ROOT / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'alerted': []}
    page = os.environ.get('PAGE_URL', '')

    for s in data['saturdays']:
        kind = 'week' if 1 < s['days_away'] <= 7 else 'tomorrow' if s['days_away'] == 1 else None
        key = f"{s['date']}:{kind}"
        if not kind or key in state['alerted']:
            continue
        name = 'Unicorn low tide' if s['tier'] == 'unicorn' else 'Almost-unicorn low tide'
        when = 'tomorrow' if kind == 'tomorrow' else f"next Saturday, {s['label'][4:-6]}"
        subject = (f"{name} {when}! {s['low_ft']} ft at {s['low_time']}" if kind == 'tomorrow'
                   else f"Save the date: {name.lower()} {when}")
        body = (f"Clear your Saturday. The tide drops to {s['low_ft']} ft at {s['low_time']} {when} "
                f"at the Half Moon Bay tide pools. Sunset is {s['sunset']}.\n\n"
                f"Leave San Francisco by {s['leave_sf']} to park at the Ritz-Carlton by {s['at_ritz']} and reach the beach "
                f"at {s['below_zero']}, when the tide drops below zero. Then follow the water down. Bring boots, a headlamp for the walk back, "
                f"and a tide pool guide.\n\n{page}\n\n"
                "Big swell can wash over the reef even on a minus tide. Check the surf, never turn your back on the ocean, "
                "and leave everything where you found it.\nReply 'stop' to unsubscribe.")
        if send_emails(subject, body) or os.environ.get('MARK_DRY_RUN'):
            state['alerted'].append(key)
    state['alerted'] = sorted(set(state['alerted']))[-50:]
    state_path.write_text(json.dumps(state, indent=1))

    for s in data['saturdays']:
        print(f"{s['label']:<18} {s['tier']:<8} {s['low_ft']:>6} ft at {s['low_time']:<8} sunset {s['sunset']}  in {s['days_away']} days")
    for m in data['misses']:
        print(f"miss: {m['label']} {m['low_ft']} ft at {m['low_time']} ({m['why']})")


if __name__ == '__main__':
    main()
