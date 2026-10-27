"""Owner-only checkout workspace. Server response is the sole active-mode signal."""
import streamlit as st


def run(client):
    st.header('Checkout Control')
    state = client.json('/admin/checkout-control')
    st.metric('Current effective mode', state['effective_mode'])
    if state['requested_mode'] != state['effective_mode']:
        st.info('Requested mode: ' + state['requested_mode'])
    for label, field in (
        ('Stripe TEST credentials', 'stripe_test_credentials_configured'),
        ('Stripe LIVE credentials', 'stripe_live_credentials_configured'),
        ('TEST webhook', 'test_webhook_configured'),
        ('LIVE webhook', 'live_webhook_configured'),
        ('Frozen Plate and confirmation email configuration', 'frozen_plate_and_email_configuration_ready'),
    ):
        st.write(label + ': ' + ('Configured' if state[field] else 'Unavailable'))
    st.write('TEST operational readiness: ' + ('Verified' if state['test_ready'] else 'Blocked'))
    st.caption(state['provider_readiness'])
    st.caption(f"Last change: {state['changed_at']} · Version {state['version']} · {state['audit_status']}")
    for blocker in state['test_blockers']:
        st.warning(blocker)
    st.caption(state.get("stripe_live_readiness", "Separate LIVE verification required"))
    st.info('LIVE unavailable: separate verified owner authorization and supervised payment acceptance required.')
    mode = st.selectbox('Requested checkout mode', ['CLOSED', 'TEST', 'LIVE'],
                        index=['CLOSED', 'TEST', 'LIVE'].index(state['requested_mode']))
    confirmation = st.text_input('Type APPLY ' + mode + ' to confirm', key='mc_checkout_confirm')
    if st.button('Save / Apply', type='primary', disabled=mode == 'LIVE'):
        result = client.checkout_mode_write({'requested_mode': mode, 'expected_version': state['version'],
                                            'confirmation': confirmation})
        if result.get('error'):
            st.error(result['error'])
        else:
            st.success('Server confirmed effective mode: ' + result['effective_mode'])
            st.rerun()
    close = st.checkbox('I confirm: close all new checkout immediately')
    if st.button('Close New Checkout', disabled=not close):
        result = client.checkout_mode_write({'requested_mode': 'CLOSED', 'expected_version': state['version'],
                                            'confirmation': 'APPLY CLOSED'})
        if result.get('error'):
            st.error(result['error'])
        else:
            st.rerun()
    st.caption('Closing preserves carts, paid orders, in-flight signed webhooks and drawing approvals.')
