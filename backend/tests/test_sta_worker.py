from app.sta_worker import sta_commands


def test_optional_spef_is_read_after_link_and_before_constraints():
    paths = {'liberty': '/tmp/library.lib', 'netlist': '/tmp/design.v',
             'spef': '/tmp/parasitics.spef', 'sdc': '/tmp/constraints.sdc'}
    commands = sta_commands(paths, 'top', '/tmp/report.json')
    assert [command.split()[0] for command in commands[1:]] == [
        'read_liberty', 'read_verilog', 'link_design', 'read_spef', 'read_sdc', 'report_checks',
    ]
    assert commands[4] == 'read_spef {/tmp/parasitics.spef}'


def test_no_spef_command_without_artifact():
    paths = {'liberty': '/tmp/library.lib', 'netlist': '/tmp/design.v', 'sdc': '/tmp/constraints.sdc'}
    commands = sta_commands(paths, 'top', '/tmp/report.json')
    assert not any(command.startswith('read_spef ') for command in commands)
