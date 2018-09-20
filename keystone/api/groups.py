#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# This file handles all flask-restful resources for /v3/groups

import flask_restful
from six.moves import http_client

from keystone.common import json_home
from keystone.common import provider_api
from keystone.common import rbac_enforcer
from keystone.common import validation
from keystone import exception
from keystone.identity import schema
from keystone.server import flask as ks_flask


ENFORCER = rbac_enforcer.RBACEnforcer
PROVIDERS = provider_api.ProviderAPIs


class GroupsResource(ks_flask.ResourceBase):
    collection_key = 'groups'
    member_key = 'group'
    get_member_from_driver = PROVIDERS.deferred_provider_lookup(
        api='identity_api', method='get_group')

    def get(self, group_id=None):
        if group_id is not None:
            return self._get_group(group_id)
        return self._list_groups()

    def _get_group(self, group_id):
        """Get a group reference.

        GET/HEAD /groups/{group_id}
        """
        ENFORCER.enforce_call(action='identity:get_group')
        return self.wrap_member(PROVIDERS.identity_api.get_group(group_id))

    def _list_groups(self):
        """List groups.

        GET/HEAD /groups
        """
        filters = ['domain_id', 'name']
        ENFORCER.enforce_call(action='identity:list_groups', filters=filters)
        hints = self.build_driver_hints(filters)
        domain = self._get_domain_id_for_list_request()
        refs = PROVIDERS.identity_api.list_groups(domain_scope=domain,
                                                  hints=hints)
        return self.wrap_collection(refs, hints=hints)

    def post(self):
        """Create group.

        POST /groups
        """
        ENFORCER.enforce_call(action='identity:create_group')
        group = self.request_body_json.get('group', {})
        validation.lazy_validate(schema.group_create, group)
        group = self._normalize_dict(group)
        group = self._normalize_domain_id(group)
        ref = PROVIDERS.identity_api.create_group(
            group, initiator=self.audit_initiator)
        return self.wrap_member(ref), http_client.CREATED

    def patch(self, group_id):
        """Update group.

        PATCH /groups/{group_id}
        """
        ENFORCER.enforce_call(action='identity:update_group')
        group = self.request_body_json.get('group', {})
        validation.lazy_validate(schema.group_update, group)
        self._require_matching_id(group)
        ref = PROVIDERS.identity_api.update_group(
            group_id, group, initiator=self.audit_initiator)
        return self.wrap_member(ref)

    def delete(self, group_id):
        """Delete group.

        DELETE /groups/{group_id}
        """
        ENFORCER.enforce_call(action='identity:delete_group')
        PROVIDERS.identity_api.delete_group(
            group_id, initiator=self.audit_initiator)
        return None, http_client.NO_CONTENT


class GroupUsersResource(flask_restful.Resource):
    def get(self, group_id):
        """Get list of users in group.

        GET/HEAD /groups/{group_id}/users
        """
        filters = ['domain_id', 'enabled', 'name', 'password_expires_at']
        target = {}
        try:
            target['group'] = PROVIDERS.identity_api.get_group(group_id)
        except exception.GroupNotFound:
            # NOTE(morgan): If we have an issue populating the group
            # data, leage target empty. This is the safest route and does not
            # leak data before enforcement happens.
            pass
        ENFORCER.enforce_call(action='identity:list_users_in_group',
                              target_attr=target, filters=filters)
        hints = ks_flask.ResourceBase.build_driver_hints(filters)
        refs = PROVIDERS.identity_api.list_users_in_group(
            group_id, hints=hints)
        return ks_flask.ResourceBase.wrap_collection(
            refs, hints=hints, collection_name='users')


class UserGroupCRUDResource(flask_restful.Resource):
    @staticmethod
    def _build_enforcement_target_attr(user_id, group_id):
        target = {}
        try:
            target['group'] = PROVIDERS.identity_api.get_group(group_id)
        except exception.GroupNotFound:
            # Don't populate group data if group is not found.
            pass

        try:
            target['user'] = PROVIDERS.identity_api.get_user(user_id)
        except exception.UserNotFound:
            # Don't populate user data if user is not found
            pass

        return target

    def get(self, group_id, user_id):
        """Check if a user is in a group.

        GET/HEAD /groups/{group_id}/users/{user_id}
        """
        ENFORCER.enforce_call(
            action='identity:check_user_in_group',
            target_attr=self._build_enforcement_target_attr(user_id, group_id))
        PROVIDERS.identity_api.check_user_in_group(user_id, group_id)
        return None, http_client.NO_CONTENT

    def put(self, group_id, user_id):
        """Add user to group.

        PUT /groups/{group_id}/users/{user_id}
        """
        ENFORCER.enforce_call(
            action='identity:add_user_to_group',
            target_attr=self._build_enforcement_target_attr(user_id, group_id))
        PROVIDERS.identity_api.add_user_to_group(
            user_id, group_id, initiator=ks_flask.build_audit_initiator())
        return None, http_client.NO_CONTENT

    def delete(self, group_id, user_id):
        """Remove user from group.

        DELETE /groups/{group_id}/users/{user_id}
        """
        ENFORCER.enforce_call(
            action='identity:remove_user_from_group',
            target_attr=self._build_enforcement_target_attr(user_id, group_id))
        PROVIDERS.identity_api.remove_user_from_group(
            user_id, group_id, initiator=ks_flask.build_audit_initiator())
        return None, http_client.NO_CONTENT


class GroupAPI(ks_flask.APIBase):
    _name = 'groups'
    _import_name = __name__
    resources = [GroupsResource]
    resource_mapping = [
        ks_flask.construct_resource_map(
            resource=GroupUsersResource,
            url='/groups/<string:group_id>/users',
            resource_kwargs={},
            rel='group_users',
            path_vars={'group_id': json_home.Parameters.GROUP_ID}),
        ks_flask.construct_resource_map(
            resource=UserGroupCRUDResource,
            url='/groups/<string:group_id>/users/<string:user_id>',
            resource_kwargs={},
            rel='group_user',
            path_vars={
                'group_id': json_home.Parameters.GROUP_ID,
                'user_id': json_home.Parameters.USER_ID})
    ]


APIs = (GroupAPI,)
