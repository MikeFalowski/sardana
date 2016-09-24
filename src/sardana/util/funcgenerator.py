import time
import threading
import math
import copy
import numpy
from sardana.sardanaevent import EventGenerator
from sardana.pool.pooltriggergate import TGEventType
from sardana.pool.pooldefs import SynchParam, SynchDomain


class FunctionGenerator(EventGenerator):

    MAX_NAP_TIME = 0.1

    def __init__(self):
        EventGenerator.__init__(self)
        self._active_domain = SynchDomain.Default
        self._passive_domain = SynchDomain.Default
        self._position_event = threading.Event()
        self._active_domain_in_use = None
        self._passive_domain_in_use = None
        self._active_events = list()
        self._passive_events = list()
        self._started = False
        self._stopped = False
        self._running = False
        self._start_time = None
        self._direction = None
        self._condition = None
        self._id = None

    def set_active_domain(self, domain):
        self._active_domain = domain

    def get_active_domain(self):
        return self._active_domain

    active_domain = property(get_active_domain, set_active_domain)

    def set_passive_domain(self, domain):
        self._passive_domain = domain

    def get_passive_domain(self):
        return self._passive_domain

    passive_domain = property(get_passive_domain, set_passive_domain)

    def set_active_domain_in_use(self, domain):
        self._active_domain_in_use = domain

    def get_active_domain_in_use(self):
        return self._active_domain_in_use

    active_domain_in_use = property(get_active_domain_in_use,
                                    set_active_domain_in_use)

    def set_passive_domain_in_use(self, domain):
        self._passive_domain_in_use = domain

    def get_passive_domain_in_use(self):
        return self._passive_domain_in_use

    passive_domain_in_use = property(get_passive_domain_in_use,
                                     set_passive_domain_in_use)

    def add_active_event(self, event):
        self._active_events.append(event)

    def set_active_events(self, events):
        self._active_events = events

    def get_active_events(self):
        return self._active_events

    active_events = property(get_active_events, set_active_events)

    def add_passive_event(self, event):
        self._passive_events.append(event)

    def set_passive_events(self, events):
        self._passive_events = events

    def get_passive_events(self):
        return self._passive_events

    passive_events = property(get_passive_events, set_passive_events)

    def set_direction(self, direction):
        self._direction = direction
        if direction == 1:
            self._condition = numpy.greater_equal
        elif direction == -1:
            self._condition = numpy.less_equal
        else:
            raise ValueError("direction can be -1 or 1 (negative or positive)")

    def get_direction(self):
        return self._direction

    direction = property(get_direction, set_direction)

    def event_received(self, *args, **kwargs):
        _, _, v = args
        self._position = v.value
        self._position_event.set()

    def start(self):
        print self.active_events
        print self.passive_events
        self._start_time = time.time()
        self._started = True
        self._position = None
        self._position_event.clear()
        self._id = 0

    def stop(self):
        self._stopped = True

    def is_started(self):
        return self._started

    def is_stopped(self):
        return self._stopped

    def is_running(self):
        return self._running

    def run(self):
        self._running = True
        try:
            while len(self.active_events) > 0 and not self.is_stopped():
                self.wait_active()
                self.fire_active()
                self.wait_passive()
                self.fire_passive()
        finally:
            self._started = False
            self._running = False
            self._stopped = False

    def sleep(self, period):
        if period <= 0:
            return
        necessary_naps = int(math.ceil(period/self.MAX_NAP_TIME))
        if necessary_naps == 0: # avoid zero ZeroDivisionError
            nap = 0
        else:
            nap = period/necessary_naps
        for _ in xrange(necessary_naps):
            if self.is_stopped():
                break
            time.sleep(nap)

    def wait_active(self):
        candidate = self.active_events[0]
        if self.active_domain_in_use == SynchDomain.Time:
            now = time.time()
            candidate += self._start_time
            self.sleep(candidate - now)
        else:
            while True:
                if self.is_stopped():
                    break
                if self._position_event.isSet():
                    self._position_event.clear()
                    now = self._position
                    if self._condition(now, candidate):
                        break
                else:
                    self._position_event.wait(self.MAX_NAP_TIME)

    def fire_active(self):
        i = 0
        while i < len(self.active_events):
            candidate = self.active_events[i]
            if self.active_domain_in_use is SynchDomain.Time:
                candidate += self._start_time
                now = time.time()
            elif self.active_domain_in_use is SynchDomain.Position:
                now = self._position
            print 'now', now
            print 'can', candidate
            if not self._condition(now, candidate):
                break
            i += 1
        self._id += i
        print "Fire Active %d" % (self._id - 1)
        self.fire_event(TGEventType.Active, self._id - 1)
        self.active_events = self.active_events[i:]
        self.passive_events = self.passive_events[i - 1:]

    def wait_passive(self):
        if self.passive_domain_in_use == SynchDomain.Time:
            now = time.time()
            candidate = self._start_time + self.passive_events[0]
            self.sleep(candidate - now)
        else:
            while True:
                if self._position_event.isSet():
                    self._position_event.clear()
                    if self._condition(self._position, self.passive_events[0]):
                        break
                else:
                    self._position_event.wait(self.MAX_NAP_TIME)
                    if self.is_stopped():
                        break

    def fire_passive(self):
        print "Fire passive %d" % (self._id - 1)
        self.fire_event(TGEventType.Passive, self._id - 1)
        self.set_passive_events(self.passive_events[1:])

    def set_configuration(self, configuration):
        # make a copy since we may inject the initial time
        configuration = copy.deepcopy(configuration)
        active_events = []
        passive_events = []
        self._direction = None
        # create short variables for commodity
        Time = SynchDomain.Time
        Position = SynchDomain.Position
        Default = SynchDomain.Default
        Initial = SynchParam.Initial
        Delay = SynchParam.Delay
        Active = SynchParam.Active
        Total = SynchParam.Total
        Repeats = SynchParam.Repeats

        for i, group in enumerate(configuration):
            # inject delay as initial time - generation will be
            # relative to the start time
            initial_param = group.get(Initial)
            if initial_param is None:
                initial_param = dict()
            if not initial_param.has_key(Time):
                delay_param = group.get(Delay)
                if delay_param.has_key(Time):
                    initial_param[Time] = delay_param[Time]
                group[Initial] = initial_param
            # determine active domain in use
            msg = "no initial value in group %d" % i
            if self.active_domain is Default:
                if initial_param.has_key(Position):
                    self.active_domain_in_use = Position
                elif initial_param.has_key(Time):
                    self.active_domain_in_use = Time
                else:
                    raise ValueError(msg)
            elif initial_param.has_key(self.active_domain):
                self.active_domain_in_use = self.active_domain
            else:
                raise ValueError(msg)
            # determine passive domain in use
            active_param = group.get(Active)
            msg = "no active value in group %d" % i
            if self.passive_domain is Default:
                if active_param.has_key(Time):
                    self.passive_domain_in_use = Time
                elif active_param.has_key(Position):
                    self.passive_domain_in_use = Position
                else:
                    raise ValueError(msg)
            elif active_param.has_key(self.passive_domain):
                self.passive_domain_in_use = self.passive_domain
            else:
                raise ValueError(msg)
            # create short variables for commodity
            active_domain_in_use = self.active_domain_in_use
            passive_domain_in_use = self.passive_domain_in_use
            total_param = group[Total]
            repeats = group[Repeats]
            active = active_param[passive_domain_in_use]
            initial_in_active_domain = initial_param[active_domain_in_use]
            initial_in_passive_domain = initial_param[passive_domain_in_use]
            total_in_active_domain = total_param[active_domain_in_use]
            total_in_passive_domain = total_param[passive_domain_in_use]

            active_event_in_active_domain = initial_in_active_domain
            active_event_in_passive_domain = initial_in_passive_domain
            for _ in xrange(repeats):
                passive_event = active_event_in_passive_domain + active
                active_events.append(active_event_in_active_domain)
                passive_events.append(passive_event)
                active_event_in_active_domain += total_in_active_domain
                active_event_in_passive_domain += total_in_passive_domain
            self.active_events = active_events
            self.passive_events = passive_events
            # determine direction
            direction = 1
            if total_in_active_domain < 0:
                direction = -1
            if self.direction is None:
                self.direction = direction
            elif self.direction != direction:
                msg= "active values indicate contradictory directions"
                raise ValueError(msg)
