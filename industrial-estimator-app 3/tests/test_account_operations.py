"""Regression tests for v0.8.x account management on an isolated test database.

Uses the shared synthetic test setup: no customer records are read or modified.
"""
from sqlalchemy import select
from tests.test_end_to_end import client, token, request
from backend.app import SessionLocal, User, RecoveryCode


def _api(method, path, headers=None, **kw):
    return client.request(method, path, headers=headers, **kw)


def test_profile_password_recovery_and_admin_user_operations():
    admin = token('demo')
    admin_pw = 'demo-pass-123'
    original = _api('GET', '/api/me', headers=admin)
    assert original.status_code == 200, original.text
    assert original.json()['role'] == 'admin'
    profile = _api('GET', '/api/profile', headers=admin)
    assert profile.status_code == 200 and profile.json()['recovery_codes_remaining'] == 0

    updated = _api('PUT', '/api/profile', headers=admin, json={
        'display_name': 'Finance Admin', 'email': 'finance@example.test', 'phone': '0201234567'})
    assert updated.status_code == 200, updated.text
    assert updated.json()['email'] == 'finance@example.test'
    assert _api('PUT', '/api/profile', headers=admin, json={'display_name':'A', 'email':'bad-email'}).status_code == 422

    unauthenticated = _api('POST', '/api/auth/users', json={'username':'hack','password':'LongPassword123', 'role':'admin','display_name':'Hack'})
    assert unauthenticated.status_code == 401

    new = _api('POST', '/api/auth/users', headers=admin, json={
        'username':'shop_user', 'display_name':'Shop Estimator', 'password':'TemporaryStr0ng!23',
        'email':'estimator@example.test', 'role':'estimator'})
    assert new.status_code == 200, new.text
    uid = new.json()['user']['id']
    assert new.json()['user']['must_change_password'] is True

    temp_login = _api('POST','/api/auth/login',json={'username':'shop_user','password':'TemporaryStr0ng!23'})
    assert temp_login.status_code == 200 and temp_login.json()['user']['must_change_password']
    temp_headers = {'Authorization':'Bearer '+temp_login.json()['token']}
    assert _api('GET','/api/me',headers=temp_headers).status_code == 200
    assert _api('GET','/api/projects',headers=temp_headers).status_code == 403
    assert _api('PUT','/api/profile',headers=temp_headers,json={'display_name':'Nope'}).status_code == 403
    invalid_change = _api('POST','/api/profile/password',headers=temp_headers,json={
        'current_password':'bad','new_password':'NewLongP@ssword_123'})
    assert invalid_change.status_code == 403
    changed = _api('POST','/api/profile/password',headers=temp_headers,json={
        'current_password':'TemporaryStr0ng!23','new_password':'NewLongP@ssword_123'})
    assert changed.status_code == 200, changed.text
    assert _api('GET','/api/me',headers=temp_headers).status_code == 401
    post_login = _api('POST','/api/auth/login',json={'username':'shop_user','password':'NewLongP@ssword_123'})
    assert post_login.status_code == 200 and not post_login.json()['user']['must_change_password']
    shop_auth = {'Authorization':'Bearer '+post_login.json()['token']}
    assert _api('GET','/api/projects',headers=shop_auth).status_code == 200
    assert _api('GET','/api/auth/users',headers=shop_auth).status_code == 403

    codes = _api('POST','/api/profile/recovery-codes',headers=shop_auth,json={'current_password':'NewLongP@ssword_123'})
    assert codes.status_code == 200, codes.text
    codes = codes.json()['codes']
    assert len(codes) == 6 and all(len(x) == 35 for x in codes)
    assert _api('GET','/api/profile/recovery-codes',headers=shop_auth).json()['remaining'] == 6
    with SessionLocal() as db:
        stored = db.scalars(select(RecoveryCode).where(RecoveryCode.user_id==uid)).all()
        assert len(stored) == 6
        assert all(codes[0] not in str(row.code_hash) for row in stored)

    assert _api('POST','/api/auth/recover',json={'username':'shop_user','recovery_code':'bad', 'new_password':'RecoverStrongPassword_09'}).status_code == 400
    recovery = _api('POST','/api/auth/recover',json={
        'username':'shop_user','recovery_code':codes[0], 'new_password':'RecoverStrongPassword_09'})
    assert recovery.status_code == 200, recovery.text
    assert _api('GET','/api/me',headers=shop_auth).status_code == 401
    assert _api('POST','/api/auth/recover',json={
        'username':'shop_user','recovery_code':codes[1], 'new_password':'AnotherStrongPass_321'}).status_code == 400

    admin_reset_invalid = _api('POST',f'/api/auth/users/{uid}/reset-password',headers=admin,
                               json={'current_password':'bad'})
    assert admin_reset_invalid.status_code == 403
    admin_reset = _api('POST',f'/api/auth/users/{uid}/reset-password',headers=admin,
                       json={'current_password':admin_pw})
    assert admin_reset.status_code == 200
    temporary_password = admin_reset.json()['temporary_password']
    assert len(temporary_password) >= 12 and temporary_password not in admin_reset.text.replace('"temporary_password":"'+temporary_password+'"','')
    enforced = _api('POST','/api/auth/login',json={'username':'shop_user','password':temporary_password})
    assert enforced.json()['user']['must_change_password']
    assert _api('GET','/api/projects',headers={'Authorization':'Bearer '+enforced.json()['token']}).status_code == 403
    assert _api('POST','/api/auth/users/'+str(uid)+'/reset-password',headers=admin,
                json={'current_password':'bad'}).status_code == 403
    # Current admin cannot edit or reset their own admin role.
    assert _api('POST','/api/auth/users/'+str(original.json()['id'])+'/reset-password',headers=admin,
                json={'current_password':admin_pw}).status_code == 403
    assert _api('PUT',f'/api/auth/users/{uid}',headers=admin,json={
        'display_name':'Shop Engineer', 'role':'engineer', 'email':'shop@example.test', 'phone':'',
        'active':False, 'admin_password':admin_pw}).status_code == 200
    assert _api('POST','/api/auth/login',json={'username':'shop_user','password':temporary_password}).status_code == 401
    assert _api('PUT',f'/api/auth/users/{uid}',headers=admin,json={
        'display_name':'Shop Engineer', 'role':'engineer', 'email':'shop@example.test', 'phone':'',
        'active':True, 'admin_password':admin_pw}).status_code == 200
    assert _api('POST','/api/auth/login',json={'username':'shop_user','password':temporary_password}).status_code == 200
    assert _api('GET','/api/auth/users',headers=admin).status_code == 200
    assert _api('PUT','/api/auth/users/'+str(original.json()['id']),headers=admin,json={
        'display_name':'Not Admin','role':'estimator','email':'','phone':'','active':False,
        'admin_password':admin_pw}).status_code == 403

    # Session revocation also affects other browser sessions.
    admin2 = token('demo')
    assert _api('POST','/api/profile/signout-all',headers=admin).status_code == 200
    assert _api('GET','/api/me',headers=admin).status_code == 401
    assert _api('GET','/api/me',headers=admin2).status_code == 401
    assert _api('POST','/api/auth/login',json={'username':'demo','password':admin_pw}).status_code == 200


def test_core_workflows_remain_available_after_account_migration():
    response = request('GET','/api/configs')
    assert response.status_code == 200
    assert {'fabricated_pallet','eot_crane','general_fabrication'}.issubset({x['product_type'] for x in response.json()})
    response = request('GET','/api/quote-templates')
    assert response.status_code == 200
