#!/usr/bin/env python3
# -*- coding: utf8 -*-

"""gitea-ldap-team-sync.py: Sync Gitea team members with LDAP groups"""

import json
import ldap
import requests
from requests.exceptions import HTTPError
import sys

__author__  = "Lukas Brocke"
__license__ = "MIT"

class GiteaAPI:
    """Gitea API wrapper"""

    def __init__(self, host, token):
        self._host = f"{host}/api/v1"
        self._params = {"token": token}

    def __get(self, path):
        try:
            r = requests.get(f"{self._host}{path}", params = self._params)
            if r.status_code != 200:
                raise GiteaAPIException(f"ERR: 'GET {r.url}' returned {r.status_code}")
            data = r.json()
        except HTTPError as http_e:
            raise GiteaAPIException(f"ERR: Gitea API request failed: {http_e}")
        except Exception as e:
            raise GiteaAPIException(f"ERR: {e}")
        else:
            return data

    def __delete(self, path):
        try:
            r = requests.delete(f"{self._host}{path}", params = self._params)
        except HTTPError as http_e:
            print(f"WARN: '{r.url}' failed: {http_e}")

    def __put(self, path):
        try:
            r = requests.put(f"{self._host}{path}", params = self._params)
        except HTTPError as http_e:
            print(f"WARN: '{r.url}' failed: {http_e}")

    def get_orgs(self):
        return self.__get("/admin/orgs")

    def get_teams(self, org_name):
        return self.__get(f"/orgs/{org_name}/teams")

    def get_members(self, team_id):
        return self.__get(f"/teams/{team_id}/members")

    def remove_member(self, team_id, user_name):
        return self.__delete(f"/teams/{team_id}/members/{user_name}")

    def add_member(self, team_id, user_name):
        return self.__put(f"/teams/{team_id}/members/{user_name}")


class GiteaAPIException(Exception):
    pass


class User:
    """Represents a unique LDAP and Gitea user"""

    def __init__(self, name):
        self._name = name
        # LDAP groups
        self._groups = set()
        # Gitea organizations
        self._orgs = dict()

    def get_name(self):
        return self._name

    def get_groups(self):
        return self._groups

    def get_orgs(self):
        return self._orgs

    def add_ldap_group(self, group):
        self._groups.add(group.lower())

    def get_org(self, org_name):
        org_name = org_name.lower()
        if org_name not in self._orgs:
            self._orgs[org_name] = GiteaOrganization(org_name)

        return self._orgs[org_name]

    def is_member_of(self, org_name, team_name):
        org_name = org_name.lower()
        team_name = team_name.lower()
        if org_name not in self._orgs:
            return False

        return team_name in self._orgs[org_name].get_teams()


class GiteaOrganization:
    def __init__(self, name):
        self._name = name.lower()
        self._teams = set()

    def get_name(self):
        return self._name

    def get_teams(self):
        return self._teams

    def add_team(self, name):
        self._teams.add(name.lower())


class Config:
    def __init__(self, path):
        with open(path, "r") as f:
            self._config = json.load(f)

    def get(self, key):
        if key not in self._config:
            raise KeyError(f"ERR: Key '{key}' not found in config")

        return self._config[key]

    def get_group_for(self, org_name, team_name):
        """Check if rule for given team exists, returns LDAP group"""

        key = f"{org_name}/{team_name}".lower()

        for group, teams in self.get("MAPPING").items():
            if key in map(str.lower, teams):
                return group

        return None


class TeamIDMap:
    """Helper class to remember mapping of Gitea team names to team ids"""

    def __init__(self, gitea_api):
        self._api = gitea_api
        self._map = {}

    def add(self, org_name, team_name, team_id):
        self._map[f"{org_name}/{team_name}".lower()] = team_id

    def get_id(self, org_name, team_name):
        org_name = org_name.lower()
        team_name = team_name.lower()
        key = f"{org_name}/{team_name}"

        if key in self._map:
            return self._map[key]

        # unknown team, try to find id via Gitea API
        try:
            # add all returned teams, not just the one requested
            for team in self._api.get_teams(org_name):
                self.add(org_name, team["name"].lower(), team["id"])
        except GiteaAPIException:
            return None
        else:
            # if team exists return id, None otherwise
            return self._map[key] if key in self._map else None


def ldap_fetch_users(config, users):
    try:
        con = ldap.initialize(config.get("LDAP_HOST"))
        con.simple_bind_s(config.get("LDAP_USER"), config.get("LDAP_PASS"))

        res = con.search_s(config.get("LDAP_SEARCH_BASE"), ldap.SCOPE_SUBTREE,
                config.get("LDAP_SEARCH_FILTER"))

        for group in res:
            # list of group cn's
            cns = group[1]["cn"]
            # list of members uid's
            members = group[1]["memberUid"]

            for user_name in members:
                user = get_user(user_name.decode("utf-8"), users)
                for cn in cns:
                    user.add_ldap_group(cn.decode("utf-8"))
    except ldap.LDAPError as e:
        sys.exit(f"ERR: Fetching users from LDAP failed: {e}")


def gitea_fetch_users(api, team_id_map, users):
    try:
        # Unfortunately, there is no fast and easy way to get all existing teams
        # and their members. Instead, the following method proved to be the
        # easiest:
        #            GET /admin/orgs
        #   ∀ orgs:  GET /orgs/{org}/teams
        #   ∀ teams: GET /teams/{id}/members
        for org in api.get_orgs():
            org_name = org["username"]
            
            for team in api.get_teams(org_name):
                team_name = team["name"]
                team_id = team["id"]

                for member in api.get_members(team_id):
                    user_name = member["username"]

                    user = get_user(user_name, users)
                    user_org = user.get_org(org_name)
                    user_org.add_team(team_name)
                    team_id_map.add(org_name, team_name, team_id)
    except GiteaAPIException as e:
        sys.exit(f"ERR: Fetching users from Gitea failed: {e}")


def get_user(user_name, users):
    for user in users:
        if user.get_name() == user_name:
            return user

    new_user = User(user_name)
    users.append(new_user)
    return new_user


if __name__ == "__main__":
    if len(sys.argv[1:]) != 1:
        sys.exit("Usage: ./gitea-ldap-team-sync.py <path/to/config.json>")

    try:
        path = sys.argv[1]
        config = Config(path)
    except IOError:
        sys.exit(f"ERR: Cannot find config file at '{path}'")
    except ValueError:
        sys.exit("ERR: Configuration file is malformed")

    api = GiteaAPI(config.get("GITEA_HOST"), config.get("GITEA_TOKEN"))
    team_id_map = TeamIDMap(api)
    users = []

    ldap_fetch_users(config, users)
    gitea_fetch_users(api, team_id_map, users)

    for user in users:
        # step 1: search for Gitea organizations that the user is a member of
        # but shouldn't be
        for org in user.get_orgs().values():
            for team_name in org.get_teams():
                # search for a rule in configuration that involves this
                # organization and team. if none is found, let the user
                # stay member of the team
                group = config.get_group_for(org.get_name(), team_name)
                if group == None:
                    continue

                # there is (at least) one rule mapping a specific LDAP group to
                # this organization and team, however the user is not member
                # of the LDAP group. therefore cancel his team membership
                if group not in user.get_groups():
                    api.remove_member(
                        team_id_map.get_id(org.get_name(), team_name),
                        user.get_name()
                    )
                    print((f"INFO: User '{user.get_name()}' removed from "
                           f"{org.get_name()}/{team_name}"))

        # step 2: add user to Gitea teams he should be member of but isn't
        mapping = config.get("MAPPING")
        for group, teams in mapping.items():
            if group not in user.get_groups():
                continue

            for team in teams:
                split = team.split("/")
                if len(split) != 2:
                    sys.exit(f"ERR: Invalid Gitea team '{team}'")

                org_name = split[0].lower()
                team_name = split[1].lower()

                # check if user already member of team
                if user.is_member_of(org_name, team_name):
                    continue

                # get team id, ignore if team couldn't be found
                team_id = team_id_map.get_id(org_name, team_name)
                if team_id == None:
                    continue

                api.add_member(team_id, user.get_name())
                print((f"INFO: User '{user.get_name()}' added to "
                       f"{org_name}/{team_name}"))
