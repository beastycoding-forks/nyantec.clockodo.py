# Copyright © 2022 nyantec GmbH <oss@nyantec.com>
# Written by Vika Shleina <vsh@nyantec.com>
#
# Provided that these terms and disclaimer and all copyright notices
# are retained or reproduced in an accompanying document, permission
# is granted to deal in this work without restriction, including un‐
# limited rights to use, publicly perform, distribute, sell, modify,
# merge, give away, or sublicence.
#
# This work is provided "AS IS" and WITHOUT WARRANTY of any kind, to
# the utmost extent permitted by applicable law, neither express nor
# implied; without malicious intent or gross negligence. In no event
# may a licensor, author or contributor be held liable for indirect,
# direct, other damage, loss, or other issues arising in any way out
# of dealing in the work, even if advised of the possibility of such
# damage or existence of a defect, except proven that it results out
# of said person's immediate fault when using the work as intended.

import os
import sys
import datetime
import click
import clockodo

# https://stackoverflow.com/questions/52053491/a-command-without-name-in-click/52069546#52069546
class DefaultCommandGroup(click.Group):
    """Create a group which can run a default command if no other commands match."""

    def command(self, *args, **kwargs):
        default_command = kwargs.pop('default_command', False)
        if default_command and not args:
            kwargs['name'] = kwargs.get('name', '<>')
        decorator = super(DefaultCommandGroup, self).command(*args, **kwargs)

        if default_command:
            def new_decorator(f):
                cmd = decorator(f)
                self.default_command = cmd.name
                return cmd

            return new_decorator

        return decorator

    def resolve_command(self, ctx, args):
        try:
            # test if the command parses
            return super(
                DefaultCommandGroup, self).resolve_command(ctx, args)
        except click.UsageError:
            # command did not parse, assume it is the default command
            args.insert(0, self.default_command)
            return super(
                DefaultCommandGroup, self).resolve_command(ctx, args)


def eprint(*args, **kwargs):
    return print(*args, file=sys.stderr, **kwargs)

def clock_entry_cb(clock):
    customer = str(clock.customer())
    project = ""
    _project = clock.project()
    if _project is not None:
        _project = str(_project)
        project = f"\nProject: {project}"
    service = str(clock.service())
    time_since = datetime.datetime.strftime(
        clock.time_since,
        clockodo.entry.ISO8601_TIME_FORMAT
    )
    if clock.time_until is None:
        time_until = ""
    else:
        time_until = "\nEnded at: " + datetime.datetime.strftime(
            clock.time_until,
            clockodo.entry.ISO8601_TIME_FORMAT
        )
    return f"""---
{clock}
Started at: {time_since}{time_until}
Customer: {customer}{project}
Service: {service}
Description: {clock.text}
---"""


def list_pages(api_call, key, cb=str):
    count_pages = None
    current_page = None

    while count_pages is None or current_page != count_pages:
        response = api_call(None if current_page == None else current_page + 1)

        for c in response[key]:
            print(cb(c))
        if "paging" not in response:
            break
        if count_pages is None:
            count_pages = response["paging"]["count_pages"]
        current_page = response["paging"]["current_page"]

@click.group()
@click.option('--user', envvar='CLOCKODO_API_USER', show_envvar=True)
@click.option('--token', envvar='CLOCKODO_API_TOKEN', show_envvar=True)
@click.pass_context
def cli(ctx, user, token):
    ctx.obj = clockodo.Clockodo(user, token)

@cli.group(cls=DefaultCommandGroup, invoke_without_command=True)
@click.pass_context
def clock(ctx):
    if not ctx.invoked_subcommand:
        ctx.invoke(current_clock)

@clock.command(default_command=True, name="current")
@click.pass_obj
def current_clock(api):
    clock = api.current_clock()
    if clock is None:
        print("No running clock")
        sys.exit(1)
    print(clock_entry_cb(clock))

@clock.command(name="stop")
@click.pass_obj
def stop_clock(api):
    clock = api.current_clock().stop()
    print("Finished:", str(clock))


@clock.command(name="new")
@click.option("--customer", type=int)
@click.option("--project", type=int, required=False)
@click.option("--service", type=int)
@click.argument("text", type=str)
@click.pass_obj
def new_clock(api, customer, project, service, text):
    customer = api.get_customer(customer)
    project = api.get_project(project) if project is not None else None
    service = api.get_service(service)
    clock = clockodo.clock.ClockEntry(
        api=api,
        customer=customer,
        project=project,
        service=service,
        text=text
    ).start()
    print(clock_entry_cb(clock))


@cli.command()
@click.option('--active', required=False, default=None, type=bool)
@click.pass_obj
def customers(api, active=None):
    list_pages(lambda p: api.list_customers(page=p, active=active), "customers")

@cli.command()
@click.option('--active', required=False, default=None, type=bool)
@click.option('--customer', required=False, default=None, type=int)
@click.pass_obj
def projects(api, active, customer):
    if customer is not None:
        customer = api.get_customer(customer)
    list_pages(lambda p: api.list_projects(page=p, customer=customer, active=active), "projects")

@cli.command()
@click.pass_obj
def services(api):
    list_pages(lambda p: api.list_services(page=p), "services")


@cli.command()
@click.argument('time_since', type=click.DateTime([clockodo.entry.ISO8601_TIME_FORMAT]), required=False)
@click.argument('time_until', type=click.DateTime([clockodo.entry.ISO8601_TIME_FORMAT]), required=False)
@click.pass_obj
def entries(api, time_since, time_until):
    if time_since is None:
        time_since = datetime.datetime.combine(
            datetime.date.today(),
            datetime.time(0, tzinfo=datetime.timezone.utc)
        )
    if time_until is None:
        time_until = datetime.datetime.combine(
            datetime.date.today() + datetime.timedelta(days=1),
            datetime.time(0, tzinfo=datetime.timezone.utc)
        )
    list_pages(
        lambda p: api.list_entries(time_since, time_until, page=p),
        "entries",
        cb=clock_entry_cb
    )

if __name__ == "__main__":
    cli()
