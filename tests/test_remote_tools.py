"""不启动本机浏览器的 MCP 原子工具与持续采集回归。"""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import UTC,datetime,timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from runbridge_hub.browser import BrowserError,BrowserService,BrowserSession
from runbridge_hub.browser_tools import Capture,Target,locate,register_tools
from runbridge_hub.managed_visual import ManagedCapture
from runbridge_hub.visual import VisualService
from runbridge_hub.visual_protocol import VisualSelection

@pytest.mark.asyncio
async def test_tabs_can_create_after_last_page_closed_and_requires_explicit_close_identity():
    view=SimpleNamespace(state='ACTIVE',expires_at=datetime.now(UTC)+timedelta(seconds=30))
    sessions=SimpleNamespace(query=AsyncMock(return_value=view))
    service=BrowserService(sessions=sessions,native_url='http://hub')
    page=SimpleNamespace(is_closed=lambda:False,on=lambda *a:None)
    entry=BrowserSession(session_id='s',node_id='n',grant_id='g',context=SimpleNamespace(new_page=AsyncMock(return_value=page)))
    service.entries['s']=entry;service.status=AsyncMock(return_value={'pages':[]})
    result=await service.tabs(session_id='s',token='t',action='new',page_id=None,timeout_ms=1000)
    assert entry.pages[result['page_id']] is page
    with pytest.raises(BrowserError,match='PAGE_ID_REQUIRED'):
        await service.tabs(session_id='s',token='t',action='close',page_id=None,timeout_ms=1000)

@pytest.mark.asyncio
async def test_ambiguous_locator_and_capture_origin_never_guess_or_accept_scripts():
    locator=SimpleNamespace(count=AsyncMock(return_value=2))
    with pytest.raises(BrowserError,match='AMBIGUOUS_TARGET'):
        await locate(page=SimpleNamespace(locator=lambda **kw:locator),target=Target(by='css',value='button'))
    methods={}
    def tool(**kw):
        def wrap(fn):methods[fn.__name__]=fn;return fn
        return wrap
    evaluate=AsyncMock(return_value={'values':{'zero':0},'url':'https://example.test','truncated':False})
    @asynccontextmanager
    async def page(**kw):yield SimpleNamespace(evaluate=evaluate)
    register_tools(tool=tool,browsers=lambda:SimpleNamespace(page=page),token=lambda:'t')
    args={'session_id':'s','page_id':'p','captures':{'zero':Capture(mode='count',selector='.missing')}}
    with pytest.raises(BrowserError,match='INVALID_ALLOWED_ORIGIN'):
        await methods['browser_capture'](**args,allowed_origins=['https://user:secret@example.test'])
    evaluate.assert_not_awaited()
    value=await methods['browser_capture'](**args,allowed_origins=['https://example.test'])
    assert value['values']['zero']==0
    payload=evaluate.call_args.kwargs
    assert payload['arg']['origins']==['https://example.test'] and 'location.origin' in payload['expression']

@pytest.mark.asyncio
async def test_managed_capture_uses_same_page_without_execution_lock_and_stops_late_frame():
    png=base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
    blocking=asyncio.Event();sent=asyncio.Event();packets=[]
    async def send(**kw):sent.set();await blocking.wait();return {'data':png}
    cdp=SimpleNamespace(send=send,detach=AsyncMock())
    page=SimpleNamespace(context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=cdp)),is_closed=lambda:False)
    entry=BrowserSession(session_id='s',node_id='n',grant_id='g');entry.pages['p']=page
    channel=SimpleNamespace(source=None,hello=False,view=SimpleNamespace(selection=None,stream_id=None))
    visual=SimpleNamespace(channel=lambda **kw:channel,clear=lambda **kw:None,publish=lambda **kw:None,active=lambda **kw:True,targets=lambda **kw:None,frame=lambda **kw:packets.append(kw))
    session=SimpleNamespace(view=SimpleNamespace(session_id='s',resource_id='r',connection_generation=2))
    source=ManagedCapture(visual=visual,session=session,entry=entry)
    await entry.lock.acquire()
    selection=await source.select(target_id='p')
    assert selection.state=='PENDING'
    await asyncio.wait_for(sent.wait(),timeout=1)
    await source.close();blocking.set();await asyncio.sleep(0)
    assert packets==[] and cdp.detach.await_count==1
    entry.lock.release()


@pytest.mark.asyncio
async def test_transient_capture_error_recovers_same_target_and_stream_after_clear():
    from playwright.async_api import Error
    png=base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
    cdp=SimpleNamespace(send=AsyncMock(side_effect=[Error("temporary"),{"data":png}]),detach=AsyncMock())
    page=SimpleNamespace(context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=cdp)),is_closed=lambda:False)
    entry=BrowserSession(session_id='s',node_id='n',grant_id='g');entry.pages['p']=page
    channel=SimpleNamespace(source=None,hello=False,view=SimpleNamespace(selection=None,stream_id=None,target_id=None))
    delivered=asyncio.Event();packets=[]
    def clear(**kw):channel.view.stream_id=None;channel.view.target_id=None
    def frame(**kw):
        assert kw['metadata'].stream_id==channel.view.stream_id
        assert kw['metadata'].target_id==channel.view.target_id=='p'
        packets.append(kw);delivered.set()
    visual=SimpleNamespace(channel=lambda **kw:channel,clear=clear,publish=lambda **kw:None,active=lambda **kw:True,targets=lambda **kw:None,frame=frame)
    session=SimpleNamespace(view=SimpleNamespace(session_id='s',resource_id='r',connection_generation=2))
    source=ManagedCapture(visual=visual,session=session,entry=entry)
    await source.select(target_id='p');expected=channel.view.stream_id
    try:
        await asyncio.wait_for(delivered.wait(),timeout=1)
        assert packets[0]['metadata'].stream_id==expected
    finally:await source.close()
