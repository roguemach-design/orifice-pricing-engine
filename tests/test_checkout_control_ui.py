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
        order.update(status='completed', lines=[{'line_id':'line-1','specifications':{'material':'304','quantity':1}}])
        def get(path,**kwargs):
            data=([{'id':'plate','current_revision':'r1','line_id':'line-1','lifecycle':'CUSTOMER_APPROVED',
                    'revisions':[{'id':'r1','number':1,'current':True,'approved':True,'approved_at':None,
                                  'created_at':None,'specifications':{}}]}]
                  if path.endswith('/drawing-archive') else {'orders':[order],'total':1} if path=='/me/order-history' else order)
            return SimpleNamespace(status_code=200,json=lambda:data)
        monkeypatch.setattr(auth,'api_get',get)
        import customer_orders_ui
        monkeypatch.setattr(customer_orders_ui,'api_get',get)
        app=customer_page_test('pages/2_My_Orders.py').run()
        assert not app.exception
        next(b for b in app.button if b.label=='View order').click().run()
        assert not app.exception
        assert any('Current drawing R1 approved' in s.value for s in app.success)
        assert all('YOUR ORDER IS IN PRODUCTION' not in s.value for s in app.success)
        if mode!='LIVE':
            assert any('NOT A REAL SALE' in w.value for w in app.warning)
