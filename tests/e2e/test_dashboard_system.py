"""Real browser, measured Live snapshots, and replay from verified artifacts."""
import time
import pytest

pytestmark = pytest.mark.e2e


def test_dashboard_live_then_replay_real(case):
    case.open()
    run_id=case.launch(backend='real',timeout=120)
    base=case.home+'runs/'+run_id+'/dashboard'
    case.page.goto(base)
    case.page.locator('#dashboard').wait_for()
    live=None
    deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        value=case.context.request.get(base+'/data').json()
        if value['source']=='live' and value.get('live_core_map'):
            live=value;break
        assert not value['terminal'], value
        time.sleep(.4)
    assert live and live['snapshot']['busy']<=live['cores'] and live['total']==100
    assert not live['verified']
    assert live['live']['worker_rss_mib'] > 0
    assert sum(len(j['cores']) for j in live['live_core_map']) == live['snapshot']['busy']
    case.page.locator('#dash-refresh').click()
    case.page.wait_for_timeout(500)
    case.page.screenshot(path=str(case.directory/'dashboard-live.png'),full_page=True)
    state=case.wait(run_id)
    assert state['state']=='SUCCEEDED',state
    case.page.locator('#dash-refresh').click()
    case.page.wait_for_function("document.querySelector('#dash-verification').textContent.startsWith('PASS')")
    value=case.context.request.get(base+'/data?episode=FCFS:0&position=.5').json()
    assert value['verified'] and value['source']=='replay'
    assert value['jobs_count']==100 and value['native_allocation']
    assert value['time_units']['simulation']=='seconds'
    assert value['time_units']['elapsed']=='wall_clock_seconds'
    assert value['window']==[0,value['horizon']]
    assert set(value['used_cores'])==set(range(value['cores']))
    assert {s['core'] for s in value['timeline']}==set(range(value['cores']))
    assert value['horizon']>1000 and value['elapsed']<120  # Separate clocks, no ms conversion.
    assert len(value['series'])<=903
    assert len(value['timeline'])<=2500
    assert '95%' in case.page.locator('#waiting-explanation').inner_text()
    assert 'giây thực' in case.page.locator('#time-explanation').inner_text()
    dashboard_theme=case.page.evaluate('getComputedStyle(document.body).backgroundColor')
    other=case.context.new_page()
    other.goto(case.home)
    assert other.evaluate('getComputedStyle(document.body).backgroundColor')==dashboard_theme
    other.goto(case.home+'runs/'+run_id)
    assert other.evaluate('getComputedStyle(document.body).backgroundColor')==dashboard_theme
    other.close()
    case.page.select_option('#timeline-view','window')
    case.page.wait_for_function("document.querySelector('#timeline-note').textContent.startsWith('Cửa sổ')")
    case.page.select_option('#timeline-view','full')
    case.page.wait_for_function("document.querySelector('#timeline-note').textContent.startsWith('Toàn episode')")
    case.page.select_option('#dash-episode','SJF:0')
    case.page.wait_for_function("document.querySelector('#dash-jobs').children.length===25")
    case.page.locator('#job-next').click()
    case.page.wait_for_function("document.querySelector('#job-page').textContent.startsWith('2 /')")
    case.page.locator('#dash-position').fill('500')
    case.page.locator('#dash-position').dispatch_event('input')
    case.page.wait_for_timeout(700)
    case.page.locator('#dash-play').click()
    case.page.wait_for_timeout(700)
    case.page.locator('#dash-play').click()
    assert not case.console_errors
    assert case.page.locator('#queue-chart').evaluate('(c)=>c.width>0')
    case.page.screenshot(path=str(case.directory/'dashboard-desktop.png'),full_page=True)
    case.page.set_viewport_size({'width':390,'height':844})
    case.page.wait_for_timeout(400)
    assert case.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
    case.page.screenshot(path=str(case.directory/'dashboard-mobile.png'),full_page=True)
