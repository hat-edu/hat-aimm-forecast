from hat import util
import hat.aio
import hat.event.server.common

from enum import Enum

import logging

mlog = logging.getLogger(__name__)

json_schema_id = None
json_schema_repo = None

_source_id = 0

from aimm.client import repl
import pandas
import numpy



class RETURN_TYPE(Enum):
    PREDICT = 1
    FIT = 2
    CREATE = 3


async def create(conf, engine):
    module = ReadingsModule()
    # module.model_control = ModelControl()

    global _source_id
    module._source = hat.event.server.common.Source(
        type=hat.event.server.common.SourceType.MODULE,
        name=__name__,
        id=_source_id)
    _source_id += 1

    module._subscription = hat.event.server.common.Subscription([
        ('aimm', '*'),
        ('gui', 'backValue', '*')])
    module._async_group = hat.aio.Group()
    module._engine = engine

    module._model_ids = []

    module._model_id = None
    module._readings = []
    module._request_id = None

    module._request_ids = {}

    return module


class ReadingsModule(hat.event.server.common.Module):

    @property
    def async_group(self):
        return self._async_group

    @property
    def subscription(self):
        return self._subscription

    async def create_session(self):
        return ReadingsSession(self._engine, self,
                               self._async_group.create_subgroup())

    def send_message(self, event, type_name):

        async def send_log_message():
            await self._engine.register(
                self._source,
                [_register_event(('gui', 'log', type_name), event.payload.data)])

        self._async_group.spawn(send_log_message)

    async def fit(self):
        if self._model_id:

            df = pandas.read_csv('../../dataset/sanatized.csv')
            goal = 'PT08.S1(CO)'
            x, y = [], []
            for i in range(48, len(df) - 24, 24):
                x.append(df[goal][i - 48:i])
                y.append(df[goal][i:i + 24])
            x, y = numpy.array(x), numpy.array(y)

            events = await self._engine.register(
                self._source,
                [_register_event(('aimm', 'fit', self._model_id),
                                 {
                                     'args': [x.tolist(), y.tolist()],
                                     'kwargs': {

                                     }
                                 }
                                 )])

            self._request_ids[events[0].event_id._asdict()['instance']] = RETURN_TYPE.FIT


    def process_aimm(self, event):

        if event.event_type[1] == 'state':

            self._model_ids = list(event.payload.data['models'].keys())

            # self._model_id = util.first(event.payload.data['models'].keys())

            if len(self._model_ids):
                self._model_id = self._model_ids[-1]

            self.send_message(event, 'model_state')

            # if self._request_type == RETURN_TYPE.PREDICT:
            #     breakpoint()

        elif event.event_type[1] == 'action':

            if event.payload.data.get('request_id')['instance'] in self._request_ids \
                    and event.payload.data.get('status') == 'DONE':

                # self._request_id = None
                request_type = self._request_ids[event.payload.data.get('request_id')['instance']]
                del self._request_ids[event.payload.data.get('request_id')['instance']]

                if request_type == RETURN_TYPE.CREATE:
                    self._model_id = str(event.payload.data.get('result'))

                    self._async_group.spawn(self.fit)

                # elif request_type == RETURN_TYPE.FIT and self._model_id:
                #     pass



    async def process_return(self, event):

        if 'model' in event.payload.data:
            model_n = event.payload.data['model']
        else:
            model_n = 'MultiOutputSVR'

        async def create_instance():

            return_id = await self._engine.register(
                self._source,
                [_register_event(('aimm', 'create_instance'),
                                 {
                                     'model_type': "air_supervision.aimm.model." + model_n,
                                     'args': [],
                                     'kwargs': {}
                                 }
                                 )])

            self._request_ids[return_id[0].event_id._asdict()['instance']] = RETURN_TYPE.CREATE

        self._async_group.spawn(create_instance)




    def _process_event(self, event_type, payload, source_timestamp=None):
        return self._engine.create_process_event(
            self._source,
            _register_event(event_type, payload, source_timestamp))


class ReadingsSession(hat.event.server.common.ModuleSession):

    def __init__(self, engine, module, group):
        self._engine = engine
        self._module = module
        self._async_group = group

    @property
    def async_group(self):
        return self._async_group

    async def process(self, changes):
        new_events = []
        for event in changes:
            if event.event_type[0] == 'aimm':
                result = self._module.process_aimm(event)
                if result:
                    new_events.extend(result)
            elif event.event_type[1] == 'backValue':
                await self._module.process_return(event)
            else:
                pass
        return new_events


def _register_event(event_type, payload, source_timestamp=None):
    return hat.event.server.common.RegisterEvent(
        event_type=event_type,
        source_timestamp=source_timestamp,
        payload=hat.event.server.common.EventPayload(
            type=hat.event.server.common.EventPayloadType.JSON,
            data=payload))
