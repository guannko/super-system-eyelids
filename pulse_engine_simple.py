#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Pulse Engine
- Heartbeat every 5 minutes
- Autosave state using AutosaveProtocolEnhanced
- Monitoring using MonitoringProtocol
- File logging and graceful shutdown
"""

import asyncio
import logging
import signal
from contextlib import suppress
from typing import Optional

from monitoring_protocol import MonitoringProtocol
from autosave_protocol_enhanced import AutosaveProtocolEnhanced, SnapshotConfig


class PulseEngine:
    def __init__(self,
                 heartbeat_interval_sec: int = 300,
                 log_file: str = "pulse_engine.log") -> None:
        self.heartbeat_interval = heartbeat_interval_sec
        self.monitoring: Optional[MonitoringProtocol] = None
        self.autosave: Optional[AutosaveProtocolEnhanced] = None
        self._tasks: list[asyncio.Task] = []
        self._running = False

        self.logger = self._setup_logging(log_file)

    def _setup_logging(self, log_file: str) -> logging.Logger:
        from logging.handlers import RotatingFileHandler
        logger = logging.getLogger("PulseEngine")
        logger.setLevel(logging.INFO)

        # Avoid adding multiple handlers if re-instantiated
        if not logger.handlers:
            handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            # Also log to console for visibility
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            logger.addHandler(console)
        return logger

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Initialize protocols
        self.monitoring = MonitoringProtocol()
        self.autosave = AutosaveProtocolEnhanced(SnapshotConfig())

        # Initialize autosave before starting loops
        try:
            await self.autosave.initialize()
        except Exception as e:
            self.logger.error(f"Autosave initialize failed: {e}")

        # Start background tasks
        self._tasks.append(asyncio.create_task(self._heartbeat_loop(), name="heartbeat_loop"))
        self._tasks.append(asyncio.create_task(self._start_monitoring(), name="monitoring_main"))
        self._tasks.append(asyncio.create_task(self._start_autosave(), name="autosave_main"))

        self.logger.info("PulseEngine started")

    async def _start_monitoring(self) -> None:
        if not self.monitoring:
            return
        try:
            await self.monitoring.start_monitoring()
        except asyncio.CancelledError:
            self.logger.info("Monitoring task cancelled")
        except Exception as e:
            self.logger.error(f"Monitoring error: {e}")

    async def _start_autosave(self) -> None:
        if not self.autosave:
            return
        try:
            await self.autosave.start()
            # autosave.start schedules internal loops; keep this task alive
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.logger.info("Autosave task cancelled")
        except Exception as e:
            self.logger.error(f"Autosave error: {e}")

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self.logger.info("Heartbeat: system alive")
                # Optionally, trigger a lightweight internal check
                if self.monitoring:
                    with suppress(Exception):
                        await self.monitoring.check_system_resources()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.logger.info("Stopping PulseEngine...")

        # Graceful stop autosave internal loops
        if self.autosave:
            try:
                self.autosave.is_running = False
                # Give internal queues time to settle
                await asyncio.sleep(0.1)
                # Close HTTP session if exists
                if getattr(self.autosave, 'session', None):
                    with suppress(Exception):
                        await self.autosave.session.close()
            except Exception as e:
                self.logger.error(f"Error stopping autosave: {e}")

        # Graceful stop monitoring
        if self.monitoring:
            try:
                self.monitoring.running = False
                # Cancel any spawned monitoring tasks
                for t in list(getattr(self.monitoring, 'tasks', [])):
                    t.cancel()
                # Close HTTP session if exists
                if getattr(self.monitoring, 'session', None):
                    with suppress(Exception):
                        await self.monitoring.session.close()
            except Exception as e:
                self.logger.error(f"Error stopping monitoring: {e}")

        # Cancel our own tasks
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with suppress(asyncio.CancelledError):
                await t
        self._tasks.clear()

        self.logger.info("PulseEngine stopped")


async def _run_engine_until_signal() -> None:
    engine = PulseEngine()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        if not stop_event.is_set():
            stop_event.set()

    # Register signal handlers for graceful shutdown (Unix only)
    with suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
    with suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    await engine.start()

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await engine.stop()


def main() -> None:
    asyncio.run(_run_engine_until_signal())


if __name__ == "__main__":
    main()
