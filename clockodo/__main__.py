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
import itertools

Iso8601 = click.DateTime([clockodo.entry.ISO8601_TIME_FORMAT])

# https://stackoverflow.com/questions/52053491/a-command-without-name-in-click/52069546#52069546
# TODO replace with https://github.com/click-contrib/click-default-group
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


def our_tz():
    return datetime.datetime.now(tz=datetime.timezone.utc).astimezone().tzinfo


def clock_entry_cb(clock):
    customer = str(clock.customer)
    project = ""
    if clock.project is not None:
        project = f"\nProject: {clock.project}"
    service = str(clock.service)
    time_since = datetime.datetime.strftime(
        clock.time_since.astimezone(our_tz()),
        clockodo.entry.ISO8601_TIME_FORMAT
    )
    if clock.time_until is None:
        time_until = ""
    else:
        time_until = "\nEnded at: " + datetime.datetime.strftime(
            clock.time_until.astimezone(our_tz()),
            clockodo.entry.ISO8601_TIME_FORMAT
        )
    return f"""---
{clock}
Started at: {time_since}{time_until}
Customer: {customer}{project}
Service: {service}
Description: {clock.text}
---"""


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
        click.echo("No running clock")
        sys.exit(1)
    click.echo(clock_entry_cb(clock))


@clock.command(name="stop")
@click.pass_obj
def stop_clock(api):
    clock = api.current_clock().stop()
    click.echo("Finished: {}".format(str(clock)))


@clock.command(name="continue")
@click.pass_obj
def continue_last_clock(api):
    current_clock = api.current_clock()
    if current_clock is not None:
        click.echo("You're already clocked in!", err=True)
        exit(1)

    # Figure out today's timespan
    time_since = datetime.datetime.combine(
        datetime.date.today(),
        datetime.time(0, tzinfo=our_tz())
    )
    time_until = datetime.datetime.combine(
        datetime.date.today() + datetime.timedelta(days=1),
        datetime.time(0, tzinfo=our_tz())
    )

    # Get the last clock entry for this period
    *_, last = api.iter_entries(time_since, time_until)

    if not isinstance(last, clockodo.entry.ClockEntry):
        click.echo("Last entry is not a clock entry!", err=True)
        exit(1)

    click.echo(clock_entry_cb(last.start()))

@clock.command(name="new")
@click.option("--customer", type=str, required=False)
@click.option("--customer-id", type=int, required=False)
@click.option("--project", type=str, required=False)
@click.option("--project-id", type=int, required=False)
@click.option("--service", type=str, required=False)
@click.option("--service-id", type=int, required=False)
@click.option("--billable", type=bool, required=False, default=None)
@click.argument("text", type=str)
@click.pass_obj
def new_clock(api, customer, customer_id, project, project_id, service, service_id, text, billable):
    if customer_id is not None:
        customer = api.get_customer(customer_id)
    elif customer is not None:
        with click.progressbar(api.iter_customers(), label="Determining customer") as bar:
            for c in bar:
                if c.name == customer:
                    customer = c
                    break
            else:
                click.echo(f"Can't find a customer named {customer}", err=True)
                exit(1)
    else:
        click.echo("One of --customer or --customer-id must be specified!")
        exit(1)

    if project_id is not None:
        project = api.get_project(project)
    elif project is not None:
        with click.progressbar(api.iter_projects(), label="Determining project") as bar:
            for p in bar:
                if p.name == project:
                    project = p
                    break
            else:
                click.echo("Can't find a project named", project, err=True)
                exit(1)
    else:
        project = None

    if service_id is not None:
        service = api.get_service(service_id)
    elif service is not None:
        with click.progressbar(api.iter_services(), label="Determining service") as bar:
            for s in bar:
                if s.name == service:
                    service = s
                    break
            else:
                click.echo(f"Can't find a service named {service}", err=True)
                exit(1)
    else:
        click.echo("One of --service or --service-id must be specified!")
        exit(1)

    assert isinstance(customer, clockodo.customer.Customer)
    assert isinstance(service, clockodo.service.Service)
    assert project is None or isinstance(project, clockodo.project.Project)

    clock = clockodo.clock.ClockEntry(
        api=api,
        customer=customer,
        project=project,
        service=service,
        text=text,
        billable=billable
    ).start()
    click.echo(clock_entry_cb(clock))


@clock.command(name="edit")
@click.option("--customer", type=int, required=False)
@click.option("--customer-id", type=int, required=False)
@click.option("--project", type=int, required=False)
@click.option("--service", type=int, required=False)
@click.option("--text", type=str, required=False)
@click.option("--time-since", type=Iso8601, required=False)
@click.option("--billable", type=bool, required=False)
@click.pass_obj
def edit_clock(api, **kwargs):
    clock = api.current_clock()
    if kwargs.get("customer_id") is not None:
        kwargs["customers_id"] = kwargs["customer_id"]
        del kwargs["customer_id"]
    elif kwargs.get("customer") is not None:
        with click.progressbar(api.iter_customers(), label="Determining customer") as bar:
            for c in bar:
                if c.name == kwargs["customer"]:
                    kwargs["customers_id"] = c.id
                    del kwargs["customer"]
                    break
            else:
                click.echo(f"Can't find a customer named {customer}", err=True)
                exit(1)

    if kwargs.get("project_id") is not None:
        kwargs["projects_id"] = kwargs["project_id"]
        del kwargs["project_id"]
    elif kwargs.get("project") is not None:
        with click.progressbar(api.iter_projects(), label="Determining project") as bar:
            for c in bar:
                if c.name == kwargs["project"]:
                    kwargs["projects_id"] = c.id
                    del kwargs["project"]
                    break
            else:
                click.echo(f"Can't find a project named {project}", err=True)
                exit(1)

    if kwargs.get("service_id") is not None:
        kwargs["services_id"] = kwargs["service_id"]
        del kwargs["service_id"]
    elif kwargs.get("service") is not None:
        with click.progressbar(api.iter_services(), label="Determining service") as bar:
            for c in bar:
                if c.name == kwargs["service"]:
                    kwargs["services_id"] = c.id
                    del kwargs["service"]
                    break
            else:
                click.echo(f"Can't find a service named {service}", err=True)
                exit(1)

    click.echo(clock_entry_cb(clock.edit(kwargs)))


@cli.command()
@click.option('--active', required=False, default=None, type=bool)
@click.pass_obj
def customers(api, active=None):
    for i in api.iter_customers(active=active):
        print(str(i))


@cli.command()
@click.option('--active', required=False, default=None, type=bool)
@click.option('--customer-id', required=False, default=None, type=int)
@click.option('--customer', required=False, default=None, type=str)
@click.pass_obj
def projects(api, active, customer, customer_id):
    if customer_id is not None:
        customer = api.get_customer(customer_id)
    elif customer is not None:
        with click.progressbar(api.iter_customers(), label="Determining customer") as bar:
            for c in bar:
                if c.name == customer:
                    customer = c
                    break
            else:
                click.echo(f"Can't find a customer named {customer}", err=True)
                exit(1)

    for i in api.iter_projects(customer=customer, active=active):
        print(str(i))

@cli.command()
@click.pass_obj
def services(api):
    for i in api.list_services()["services"]:
        print(str(i))


@cli.command()
@click.argument('time_since', type=Iso8601, required=False)
@click.argument('time_until', type=Iso8601, required=False)
@click.pass_obj
def entries(api, time_since, time_until):
    if time_since is None:
        time_since = datetime.datetime.combine(
            datetime.date.today(),
            datetime.time(0, tzinfo=our_tz())
        )
    if time_until is None:
        time_until = datetime.datetime.combine(
            datetime.date.today() + datetime.timedelta(days=1),
            datetime.time(0, tzinfo=our_tz())
        )

    def pairwise_with_last_none(iterable):
        """Like itertools.pairwise(), but returns `(last, None)`
        instead of `(last-1, last)` as the last entry."""
        main, peek = itertools.tee(iterable)
        # Advance the "peek" iterator by one entry
        next(peek, None)
        # Zip entries in pairs like this: ABCDEFG -> (AB, BC, CD, DE, EF, FG, G_)
        yield from itertools.zip_longest(main, peek, fillvalue=None)

    break_count = 0
    total_break_duration = datetime.timedelta(0)
    total_work_time = datetime.timedelta(0)
    entries = pairwise_with_last_none(api.iter_entries(time_since, time_until))
    for entry, next_entry in entries:
        click.echo(clock_entry_cb(entry))
        if entry.duration is not None:
            total_work_time += datetime.timedelta(seconds=entry.duration)
        else:
            total_work_time += datetime.datetime.now(tz=datetime.timezone.utc) - entry.time_since

        if entry.time_until is not None and next_entry is not None:
            next_since = next_entry.time_since
            break_duration = next_since - entry.time_until
            total_break_duration += break_duration
            if break_duration > datetime.timedelta(0):
                click.echo("Break: {}".format(clockodo.entry.format_timedelta(break_duration)))
                break_count += 1

    click.echo("Total work time: {}".format(clockodo.entry.format_timedelta(total_work_time)))
    click.echo("Breaks: {}, total duration: {}".format(
        break_count,
        clockodo.entry.format_timedelta(total_break_duration)
    ))
if __name__ == "__main__":
    cli()
