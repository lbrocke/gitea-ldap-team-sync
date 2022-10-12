# gitea-ldap-team-sync.py

> Sync Gitea team members with LDAP groups

~~Unfortunately, Gitea doesn't ([yet](https://github.com/go-gitea/gitea/issues/2121)) support syncing organization and team memberships based on LDAP groups.~~ This script will manage team memberships based on a simple LDAP group to Gitea team mapping.

Note: Gitea added support for this in [v1.17.0](https://github.com/go-gitea/gitea/pull/16299).

## Configuration

This script makes use of the Gitea API, therefore you'll need to create an access token (Settings -> Applications -> Manage Access Tokens) for a user with admin privileges.

The configuration parameters in `config.json` should be straightforward. To configure which LDAP groups should be synchronized, edit the `MAPPING` section.

**Example:**
```
MAPPING": {
	"adm": ["admin/Owners", "staff/Admins"]
}
```

This will add users with LDAP group "adm" to the team "Owners" in organization "admin" and team "Admins" in organization "staff". Users in any of these two teams *without* the "adm" LDAP group will be removed. Gitea teams that aren't mentioned anywhere in the mapping won't be modified.

Run
`./gitea-ldap-team-sync.py config.json` regularly (e.g. Cronjob) to start syncing memberships.

## License

[MIT](LICENSE)
