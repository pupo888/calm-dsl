import time
import warnings
import click
import arrow
from prettytable import PrettyTable

from .utils import get_name_query, highlight_text
from calm.dsl.builtins import ProjectValidator


def get_projects(obj, name, filter_by, limit, offset, quiet):
    """ Get the projects, optionally filtered by a string"""

    client = obj.get("client")
    config = obj.get("config")

    params = {"length": limit, "offset": offset}
    filter_query = ""
    if name:
        filter_query = get_name_query([name])
    if filter_by:
        filter_query = filter_query + ";" + filter_by if name else filter_by
    if filter_query.startswith(";"):
        filter_query = filter_query[1:]

    # right now there is no support for filter by state of project

    if filter_query:
        params["filter"] = filter_query

    res, err = client.project.list(params=params)

    if err:
        pc_ip = config["SERVER"]["pc_ip"]
        warnings.warn(UserWarning("Cannot fetch projects from {}".format(pc_ip)))
        return

    json_rows = res.json()["entities"]

    if quiet:
        for _row in json_rows:
            row = _row["status"]
            click.echo(highlight_text(row["name"]))
        return

    table = PrettyTable()
    table.field_names = [
        "NAME",
        "DESCRIPTION",
        "STATE",
        "OWNER",
        "USER COUNT",
        "CREATED ON",
        "LAST UPDATED",
        "UUID",
    ]

    for _row in json_rows:
        row = _row["status"]
        metadata = _row["metadata"]

        creation_time = arrow.get(metadata["creation_time"]).timestamp
        last_update_time = arrow.get(metadata["last_update_time"])

        table.add_row(
            [
                highlight_text(row["name"]),
                highlight_text(row["description"]),
                highlight_text(row["state"]),
                highlight_text(metadata["owner_reference"]["name"]),
                highlight_text(len(row["resources"]["user_reference_list"])),
                highlight_text(time.ctime(creation_time)),
                "{}".format(last_update_time.humanize()),
                highlight_text(metadata["uuid"])
            ]
        )
    click.echo(table)


def get_project(client, name):

    params = {"filter": "name=={}".format(name)}

    res, err = client.project.list(params=params)
    if err:
        raise Exception("[{}] - {}".format(err["code"], err["error"]))

    response = res.json()
    entities = response.get("entities", None)
    project = None
    if entities:
        if len(entities) != 1:
            raise Exception("More than one project found - {}".format(entities))

        click.echo(">> {} found >>".format(name))
        project = entities[0]
    else:
        raise Exception(">> No project found with name {} found >>".format(name))

    project_id = project["metadata"]["uuid"]
    click.echo(">> Fetching project details")
    res, err = client.project.read(project_id)  # for getting additional fields
    if err:
        raise Exception("[{}] - {}".format(err["code"], err["error"]))

    project = res.json()
    return project


def delete_project(obj, project_names):

    client = obj.get("client")

    for project_name in project_names:
        project = get_project(client, project_name)
        project_id = project["metadata"]["uuid"]
        res, err = client.project.delete(project_id)
        if err:
            raise Exception("[{}] - {}".format(err["code"], err["error"]))
        click.echo("Project {} deleted".format(project_name))


def create_project(client, payload):

    name = payload["project_detail"]["name"]

    # check if project having same name exists
    click.echo("Searching for projects having same name ")
    params = {"filter": "name=={}".format(name)}
    res, err = client.project.list(params=params)
    if err:
        return None, err

    response = res.json()
    entities = response.get("entities", None)
    if entities:
        if len(entities) > 0:
            err_msg = "Project with name {} already exists". format(name)
            err = {"error": err_msg, "code": -1}
            return None, err

    click.echo("No project with same name exists")
    click.echo("Creating the project {}". format(name))

    # validating the payload
    ProjectValidator.validate_dict(payload)
    payload = {
        'api_version': "3.0",     # TODO Remove by a constant
        'metadata': {
            'kind': 'project'
        },
        'spec': payload
    }

    return client.project.create(payload)


def describe_project(obj, project_name):

    client = obj.get("client")
    project = get_project(client, project_name)

    click.echo("\n----Project Summary----\n")
    click.echo(
        "Name: "
        + highlight_text(project_name)
        + " (uuid: "
        + highlight_text(project["metadata"]["uuid"])
        + ")"
    )

    click.echo("Status: " + highlight_text(project["status"]["state"]))
    click.echo(
        "Owner: " + highlight_text(project["metadata"]["owner_reference"]["name"])
    )

    created_on = arrow.get(project["metadata"]["creation_time"])
    past = created_on.humanize()
    click.echo(
        "Created on: {} ({})".format(
            highlight_text(time.ctime(created_on.timestamp)), highlight_text(past)
        )
    )

    acp_list = project["status"]["access_control_policy_list_status"]
    click.echo("\nUsers, Group and Roles: ", nl=False)
    if not acp_list:
        click.echo(highlight_text("None"))
    else:
        click.echo("")
        table = PrettyTable()
        table.field_names = [
            "Name",
            "Role"
        ]

        for acp in acp_list:
            role = acp["access_control_policy_status"]["resources"]["role_reference"]
            users = acp["access_control_policy_status"]["resources"]["user_reference_list"]

            for user in users:
                table.add_row(
                    [
                        highlight_text(user["name"]),
                        highlight_text(role["name"])
                    ]
                )
        click.echo(table)

    click.echo("\nInfrastructure: ", nl=False)

    accounts = project["status"]["project_status"]["resources"]["account_reference_list"]
    account_name_uuid_map = client.account.get_name_uuid_map()
    account_uuid_name_map = {v: k for k, v in account_name_uuid_map.items()}    # TODO check it

    if not accounts:
        click.echo(highlight_text("None"))
    else:
        click.echo("")
        table = PrettyTable()
        table.field_names = [
            "Name",
            "UUID"
        ]
        for account in accounts:    # TODO display in table
            account_id = account["uuid"]
            account_name = account_uuid_name_map[account_id]
            table.add_row(
                [
                    highlight_text(account_name),
                    highlight_text(account_id)
                ]
            )
        click.echo(table)

    subnets = project["status"]["project_status"]["resources"]["subnet_reference_list"]
    click.echo("\nSubnets registered", nl=False)
    if not subnets:
        click.echo(highlight_text("None"))
    else:
        click.echo("")
        table = PrettyTable()
        table.field_names = [
            "Name",
            "UUID"
        ]

        for subnet in subnets:
            table.add_row(
                [
                    highlight_text(subnet["name"]),
                    highlight_text(subnet["uuid"])
                ]
            )
        click.echo(table)
