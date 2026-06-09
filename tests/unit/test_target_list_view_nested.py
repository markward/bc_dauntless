from engine.ui.target_list_view import TargetListView


def test_subsystem_toggle_action_tracks_expansion():
    view = TargetListView()
    handled = view.dispatch_event_subsystem_toggle("Enterprise", "Phasers")
    assert handled is True
    assert "Enterprise/Phasers" in view._expanded_subsystems
    # Toggling again collapses it.
    view.dispatch_event_subsystem_toggle("Enterprise", "Phasers")
    assert "Enterprise/Phasers" not in view._expanded_subsystems
