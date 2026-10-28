from copy import deepcopy
from streamlit.testing.v1 import AppTest


class Client:
    def __init__(self):
        self.state = dict(effective_mode='CLOSED', requested_mode='CLOSED', version=1,
                          changed_at='2026-10-27', audit_status='Versioned database transaction',
                          provider_readiness='Provider binding must be verified', test_ready=True,
                          test_blockers=[], stripe_test_credentials_configured=True,
                          stripe_live_credentials_configured=True, test_webhook_configured=True,
                          live_webhook_configured=True, frozen_plate_and_email_configuration_ready=True)
        self.writes = []
    def json(self,path):
        assert path == '/admin/checkout-control'
        return deepcopy(self.state)
    def checkout_mode_write(self,body):
        self.writes.append(body)
        if body['confirmation'] != 'APPLY ' + body['requested_mode']:
            return {'error':'Deliberate confirmation required'}
        self.state.update(effective_mode=body['requested_mode'],requested_mode=body['requested_mode'],
                          version=self.state['version']+1)
        return deepcopy(self.state)


ui_client = None


def test_owner_selector_deliberate_save_live_disabled_and_close():
    global ui_client
    ui_client = Client()
    app = AppTest.from_string('from test_checkout_control_ui import ui_client\nfrom manufacturing_control.checkout import run\nrun(ui_client)').run()
    assert not app.exception
    assert app.selectbox[0].options == ['CLOSED','TEST','LIVE']
    app.selectbox[0].set_value('TEST').run()
    assert app.metric[0].value == 'CLOSED'  # selection is not activation
    next(b for b in app.button if b.label == 'Save / Apply').click().run()
    assert app.error[0].value == 'Deliberate confirmation required'
    app.text_input[0].set_value('APPLY TEST').run()
    next(b for b in app.button if b.label == 'Save / Apply').click().run()
    assert app.metric[0].value == 'TEST'
    app.selectbox[0].set_value('LIVE').run()
    assert next(b for b in app.button if b.label == 'Save / Apply').disabled
    next(c for c in app.checkbox if c.label.startswith('I confirm:')).check().run()
    next(b for b in app.button if b.label == 'Close New Checkout').click().run()
    assert app.metric[0].value == 'CLOSED'
    assert ui_client.writes[-1]['requested_mode'] == 'CLOSED'


def test_my_orders_cannot_describe_test_approval_as_production(monkeypatch):
    import auth
    from ui_harness import customer_page_test
    from types import SimpleNamespace
    monkeypatch.setattr(auth,'render_auth_sidebar',lambda **kwargs:None)
    monkeypatch.setattr(auth,'require_login',lambda *args:None)
    for mode in ('OWNER TEST','TEST','LIVE'):
        order={'id':'order','payment_mode':mode,'order_number_display':'OP-TEST','quote_payload':{}}
        def get(path,**kwargs):
            data=([{'id':'plate','current_revision':'r1','line_id':'line-1','lifecycle':'CUSTOMER_APPROVED'}]
                  if path.endswith('/frozen-plates') else [order] if path=='/me/orders' else order)
            return SimpleNamespace(status_code=200,json=lambda:data)
        monkeypatch.setattr(auth,'api_get',get)
        app=customer_page_test('pages/2_My_Orders.py').run()
        assert not app.exception
        if mode=='LIVE':
            assert any(s.value=='YOUR ORDER IS IN PRODUCTION' for s in app.success)
        else:
            assert app.dataframe[0].value['Mode'].iloc[0]=='TEST / NOT A REAL SALE'
            assert any('NOT A REAL SALE' in w.value for w in app.warning)
            assert all('YOUR ORDER IS IN PRODUCTION' not in s.value for s in app.success)
