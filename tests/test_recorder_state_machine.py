"""Tests for recording state machine."""
import pytest
from recap.daemon.recorder.state_machine import (
    RecorderState,
    RecorderStateMachine,
    InvalidTransition,
)


class TestRecorderStateMachine:
    def test_initial_state_is_idle(self):
        sm = RecorderStateMachine()
        assert sm.state == RecorderState.IDLE

    def test_can_start_recording_from_idle(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        assert sm.state == RecorderState.RECORDING
        assert sm.current_org == "disbursecloud"

    def test_cannot_start_recording_when_already_recording(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        with pytest.raises(InvalidTransition):
            sm.start_recording(org="personal")

    def test_can_stop_recording(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        sm.stop_recording()
        assert sm.state == RecorderState.PROCESSING

    def test_cannot_stop_when_not_recording(self):
        sm = RecorderStateMachine()
        with pytest.raises(InvalidTransition):
            sm.stop_recording()

    def test_processing_completes_to_idle(self):
        sm = RecorderStateMachine()
        sm.start_recording(org="disbursecloud")
        sm.stop_recording()
        sm.processing_complete()
        assert sm.state == RecorderState.IDLE
        assert sm.current_org is None

    def test_arm_from_idle(self):
        sm = RecorderStateMachine()
        sm.arm(org="disbursecloud")
        assert sm.state == RecorderState.ARMED
        assert sm.current_org == "disbursecloud"

    def test_disarm_to_idle(self):
        sm = RecorderStateMachine()
        sm.arm(org="disbursecloud")
        sm.disarm()
        assert sm.state == RecorderState.IDLE

    def test_detected_from_armed(self):
        sm = RecorderStateMachine()
        sm.arm(org="disbursecloud")
        sm.detected(org="disbursecloud")
        assert sm.state == RecorderState.DETECTED

    def test_detected_from_idle(self):
        sm = RecorderStateMachine()
        sm.detected(org="disbursecloud")
        assert sm.state == RecorderState.DETECTED

    def test_start_recording_from_detected(self):
        sm = RecorderStateMachine()
        sm.detected(org="disbursecloud")
        sm.start_recording(org="disbursecloud")
        assert sm.state == RecorderState.RECORDING

    def test_decline_from_detected(self):
        sm = RecorderStateMachine()
        sm.detected(org="personal")
        sm.decline()
        assert sm.state == RecorderState.IDLE
        assert sm.current_org is None

    def test_state_change_callback(self):
        changes = []
        sm = RecorderStateMachine(
            on_state_change=lambda old, new: changes.append((old, new))
        )
        sm.start_recording(org="disbursecloud")
        sm.stop_recording()
        assert len(changes) == 2
        assert changes[0] == (RecorderState.IDLE, RecorderState.RECORDING)
        assert changes[1] == (RecorderState.RECORDING, RecorderState.PROCESSING)

    def test_full_lifecycle(self):
        sm = RecorderStateMachine()
        sm.arm(org="disbursecloud")
        sm.detected(org="disbursecloud")
        sm.start_recording(org="disbursecloud")
        sm.stop_recording()
        sm.processing_complete()
        assert sm.state == RecorderState.IDLE
