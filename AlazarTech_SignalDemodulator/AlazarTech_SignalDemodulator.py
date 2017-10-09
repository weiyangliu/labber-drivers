import numpy as np

import InstrumentDriver
import AlazarTech_SignalDemodulator_Wrapper as AlazarDig


class Driver(InstrumentDriver.InstrumentWorker):
    """This class implements the AlazarTech card driver."""

    def performOpen(self, options={}):
        """Perform the operation of opening the instrument connection."""
        # keep track of sampled records
        self.data = {}
        self.dt = 1.0
        # open connection
        boardId = int(self.comCfg.address)
        timeout = self.dComCfg['Timeout']
        self.dig = AlazarDig.AlazarTechDigitizer(systemId=1,
                boardId=boardId, timeout=timeout)
        self.dig.testLED()

    def performClose(self, bError=False, options={}):
        """Perform the close instrument connection operation."""
        # try to remove buffers
        self.dig.removeBuffersDMA()
        # remove digitizer object
        del self.dig

    def performSetValue(self, quant, value, sweepRate=0.0, options={}):
        """Perform the Set Value instrument operation. This function
        should return the actual value set by the instrument.
        """
        # start with setting current quant value
        quant.setValue(value)
        # don't do anything until all options are set, then set
        # complete config
        if self.isFinalCall(options):
            self.setConfiguration()
        return value

    def performGetValue(self, quant, options={}):
        """Perform the Get Value instrument operation."""
        # only implemented for records
        if quant.name in ('Channel A - Flattened data',
                          'Channel B - Flattened data',
                          'Time average',
                          'Value - Single shot',
                          'Value'):
            # special case for hardware looping
            if self.isHardwareLoop(options):
                return self.getSignalHardwareLoop(quant, options)
            # check if first call, if so get new records
            if self.isFirstCall(options):
                # clear trace buffer
                self.data = {}
                # read records
                if self.getValue('NPT AsyncDMA Enabled'):
                    self.getRecordsDMA(
                        hardware_trig=self.isHardwareTrig(options))
                else:
                    self.getRecordsSinglePort()
            # return correct data
            if quant.name not in self.data:
                self.getIQData()
            if quant.name in ('Channel A - Flattened data',
                              'Channel B - Flattened data',
                              'Time average'):
                return quant.getTraceDict(self.data[quant.name],
                                          dt=self.dt)
            else:
                return self.data[quant.name]
        else:
            # just return the quantity value
            return quant.getValue()

    def performArm(self, quant_names, options={}):
        """Perform the instrument arm operation."""
        # get config
        bGetChA = bool(self.getValue('Channel A - Enabled'))
        bGetChB = bool(self.getValue('Channel B - Enabled'))
        nSample = int(self.getValue('Number of samples'))
        nRecord = int(self.getValue('Number of records'))
        recordsPerBuffer = int(self.getValue('Records per buffer'))
        maxBufferSize = int(self.getValue('Max buffer size'))
        nMaxBuffer = int(self.getValue('Max number of buffers'))
        if (not bGetChA) and (not bGetChB):
            return
        # configure and start acquisition
        if self.isHardwareLoop(options):
            # in hardware looping, number of records is set by
            # the hardware looping
            (seq_no, n_seq) = self.getHardwareLoopIndex(options)
            # need to re-configure the card since record size was not
            # known at config
            self.dig.readRecordsDMA(bGetChA, bGetChB,
                nSample, n_seq,
                bConfig=True, bArm=True, bMeasure=False,
                maxBuffers=maxBuffers,
                maxBufferSize=maxBufferSize)
        else:
            # if not hardware looping, just trigger the card, buffers
            # are already configured
            self.dig.readRecordsDMA(bGetChA, bGetChB,
                nSample, nRecord,
                bConfig=False, bArm=True, bMeasure=False,
                maxBuffers=maxBuffers,
                maxBufferSize=maxBufferSize)

    def _callbackProgress(self, progress):
        """Report progress to server, as text string."""
        s = 'Acquiring records (%.0f%%).' % (100 * progress)
        self.reportStatus(s)

    def getSignalHardwareLoop(self, quant, options):
        """Get data from round-robin type averaging."""
        (seq_no, n_seq) = self.getHardwareLoopIndex(options)
        # if first sequence call, get data
        if seq_no == 0 and self.isFirstCall(options):
            bGetChA = bool(self.getValue('Channel A - Enabled'))
            bGetChB = bool(self.getValue('Channel B - Enabled'))
            nSample = int(self.getValue('Number of samples'))
            maxBufferSize = int(self.getValue('Max buffer size'))
            maxBuffers = int(self.getValue('Max number of buffers'))
            # show status before starting acquisition
            self.reportStatus('Digitizer - Waiting for signal')
            # get data
            self.data = self.dig.readRecordsDMA(bGetChA, bGetChB,
                nSample, n_seq,
                bConfig=False, bArm=False, bMeasure=True,
                funcStop=self.isStopped,
                funcProgress=self._callbackProgress,
                firstTimeout=self.dComCfg['Timeout'] + 180.0,
                maxBuffers=maxBuffers, maxBufferSize=maxBufferSize)
        # after getting data, pick values to return
        return quant.getTraceDict(self.data[quant.name], dt=self.dt)

    def setConfiguration(self):
        """Set digitizer configuration based on driver settings."""
        sampleRateIndex = self.getValueIndex('Sample rate')
        # clock configuration
        SourceId = int(self.getCmdStringFromValue('Clock source'))
        if self.getValue('Clock source') == 'Internal':
            # internal
            SampleRateId = int(self.getCmdStringFromValue('Sample rate'), 0)
            lFreq = [1E3, 2E3, 5E3, 10E3, 20E3, 50E3, 100E3, 200E3,
                     500E3, 1E6, 2E6, 5E6, 10E6, 20E6, 50E6, 100E6,
                     200E6, 500E6, 1E9, 1.2E9, 1.5E9, 2E9, 2.4E9, 3E9,
                     3.6E9, 4E9]
            Decimation = 0
        elif self.getValue('Clock source') == '10 MHz Reference' and \
                self.getModel() in ('9373', '9360'):
            # 10 MHz ref, for 9373 - decimation is 1
            # for now don't allow DES mode; talk to Simon about best
            # implementation
            lFreq = [1E3, 2E3, 5E3, 10E3, 20E3, 50E3, 100E3, 200E3,
                     500E3, 1E6, 2E6, 5E6, 10E6, 20E6, 50E6, 100E6,
                     200E6, 500E6, 1E9, 1.2E9, 1.5E9, 2E9, 2.4E9, 3E9,
                     3.6E9, 4E9]
            SampleRateId = int(lFreq[sampleRateIndex])
            Decimation = 0
        else:
            # 10 MHz ref, use 1GHz rate + divider; divider must be 1, 2,
            # 4, or multiple of 10
            SampleRateId = int(1E9)
            lFreq = [1E3, 2E3, 5E3, 10E3, 20E3, 50E3, 100E3, 200E3,
                     500E3, 1E6, 2E6, 5E6, 10E6, 20E6, 50E6, 100E6,
                     250E6, 500E6, 1E9]
            Decimation = int(1E9 / lFreq[sampleRateIndex])
        self.dig.AlazarSetCaptureClock(SourceId, SampleRateId, 0,
                                       Decimation)
        # define time step from sample rate
        self.dt = 1.0 / lFreq[sampleRateIndex]
        # configure inputs
        chnls = {1: 'Channel A', 2: 'Channel B'}
        for n in (1, 2):
            if self.getValue('%s - Enabled' % chnls[n]):
                # coupling and range
                if self.getModel() in ('9373', '9360'):
                    # these options are not available for these models,
                    # set to default
                    Coupling = 2
                    InputRange = 7
                    Impedance = 2
                else:
                    Coupling = int(self.getCmdStringFromValue('%s - '
                            'Coupling' % chnls[n]))
                    InputRange = int(self.getCmdStringFromValue('%s - '
                            'Range' % chnls[n]))
                    Impedance = int(self.getCmdStringFromValue('%s - '
                            'Impedance' % chnls[n]))
                # set coupling, input range, impedance
                self.dig.AlazarInputControl(n, Coupling, InputRange,
                                            Impedance)
                # bandwidth limit, only for model 9870
                if self.getModel() in ('9870',):
                    self.dig.AlazarSetBWLimit(n, 0)

        # configure trigger
        Source = int(self.getCmdStringFromValue('Trigger source'))
        Slope = int(self.getCmdStringFromValue('Trigger slope'))
        Delay = self.getValue('Trigger delay')
        timeout = self.dComCfg['Timeout']
        # trigger level is relative to full range
        trigLevel = self.getValue('Trigger level')
        vAmp = np.array([4, 2, 1, 0.4, 0.2, 0.1, .04], dtype=float)
        if self.getValue('Trigger source') == 'Channel A':
            maxLevel = vAmp[self.getValueIndex('Channel A - Range')]
        elif self.getValue('Trigger source') == 'Channel B':
            maxLevel = vAmp[self.getValueIndex('Channel B - Range')]
        elif self.getValue('Trigger source') == 'External':
            maxLevel = 5.0
        elif self.getValue('Trigger source') == 'Immediate':
            maxLevel = 5.0
            # set timeout to very short with immediate triggering
            timeout = 0.001
        # convert relative level to U8
        if abs(trigLevel) > maxLevel:
            trigLevel = maxLevel * np.sign(trigLevel)
        Level = int(128 + 127 * trigLevel / maxLevel)
        # set configuration
        self.dig.AlazarSetTriggerOperation(0, 0, Source, Slope, Level)

        # configure external input, if in use
        if self.getValue('Trigger source') == 'External':
            Coupling = int(self.getCmdStringFromValue('Trigger coupling'))
            self.dig.AlazarSetExternalTrigger(Coupling)

        # set trigger delay and timeout
        Delay = int(self.getValue('Trigger delay') / self.dt)
        self.dig.AlazarSetTriggerDelay(Delay)
        self.dig.AlazarSetTriggerTimeOut(time=timeout)
        # configure memory buffers, only possible when using DMA read
        bGetChA = bool(self.getValue('Channel A - Enabled'))
        bGetChB = bool(self.getValue('Channel B - Enabled'))
        nPostSize = int(self.getValue('Number of samples'))
        nRecord = int(self.getValue('Number of records'))
        maxBufferSize = int(self.getValue('Max buffer size'))
        maxBuffers = int(self.getValue('Max number of buffers'))
        # configure DMA read
        self.dig.readRecordsDMA(bGetChA, bGetChB,
            nPostSize, nRecord,
            bConfig=True, bArm=False, bMeasure=False,
            maxBuffers=maxBuffers, maxBufferSize=maxBufferSize)

    def getRecordsDMA(self, hardware_trig=False):
        """Resample the data with DMA."""
        # get channels in use
        bGetChA = bool(self.getValue('Channel A - Enabled'))
        bGetChB = bool(self.getValue('Channel B - Enabled'))
        nPostSize = int(self.getValue('Number of samples'))
        nRecord = int(self.getValue('Number of records'))
        maxBufferSize = int(self.getValue('Max buffer size'))
        maxBuffers = int(self.getValue('Max number of buffers'))
        # in hardware triggering mode, there is no noed to re-arm
        # the card
        bArm = not hardware_trig
        # get data
        self.data = self.dig.readRecordsDMA(bGetChA, bGetChB,
            nPostSize, nRecord,
            bConfig=False, bArm=bArm, bMeasure=True,
            funcStop=self.isStopped,
            maxBuffers=maxBuffers, maxBufferSize=maxBufferSize)

    def getRecordsSinglePort(self):
        """Resample the data."""
        # get channels in use
        bGetChA = bool(self.getValue('Channel A - Enabled'))
        bGetChB = bool(self.getValue('Channel B - Enabled'))
        nPreSize = int(self.getValue('Pre-trigger samples'))
        nPostSize = int(self.getValue('Number of samples'))
        nRecord = int(self.getValue('Number of records'))
        if (not bGetChA) and (not bGetChB):
            return

        model = self.getModel()
        if model == '9870':
            pAlgn = 64
            rAlgn = 256
            nPreAlgn = pAlgn * ((nPreSize + pAlgn - 1) // pAlgn)
            nPostAlgn = pAlgn * ((nPostSize + pAlgn - 1) // pAlgn)
            nTotal = rAlgn * ((nPreAlgn + nPostAlgn + rAlgn - 1) // rAlgn)
            nPostAlgn = nTotal - nPreAlgn
            start = nPreAlgn - nPreSize
            end = start + nPreSize + nPostSize
        else:
            raise NotImplementedError('Model ATS%s is not yet supported.'
                                      % model)

        self.dig.AlazarSetRecordSize(nPreAlgn, nPostAlgn)
        self.dig.AlazarSetRecordCount(nRecord)
        # start aquisition
        self.dig.AlazarStartCapture()
        nTry = self.dComCfg['Timeout'] / 0.05
        while nTry and self.dig.AlazarBusy() and not self.isStopped():
            # sleep for a while to save resources, then try again
            self.wait(0.050)
            nTry -= 1
        # check if timeout occurred
        if nTry <= 0:
            self.dig.AlazarAbortCapture()
            raise TimeoutError('Acquisition timed out.')
        # check if user stopped
        if self.isStopped():
            self.dig.AlazarAbortCapture()
            return

        # read data for channels in use
        if bGetChA:
            records = self.dig.readRecordsSinglePort(1)
            self.data['Channel A - Flattened data'] = \
                    records[:,start:end]
        if bGetChB:
            records = self.dig.readRecordsSinglePort(2)
            self.data['Channel B - Flattened data'] = \
                    records[:,start:end] 

    def getIQData(self):
        """Calculate complex signal from data and reference."""
        sTimeAverage = 'Time average'
        sValue = 'Value'
        sSingleShot = 'Value - Single shot'

        self.data[sTimeAverage] = np.NaN
        self.data[sSingleShot] = np.NaN
        self.data[sValue] = np.NaN
        
        # get parameters
        dFreq = self.getValue('Demodulation frequency')
        skipStart = self.getValue('Skip start')
        nSegment = int(self.getValue('Number of records'))
        # get input data from dictionary, dictionary format:
        # {'y': value, 't0': t0, 'dt': dt}
        vData = self.data['Channel A - Flattened data']
        nTotLength = vData.size
        dt = self.dt
        skipIndex = int(round(skipStart / dt))
        length = 1 + int(round(self.getValue('Demodulation length') / dt))
        segmentLength = int(nTotLength / nSegment)
        length = min(length, segmentLength - skipIndex)
        if length < 1:
            return

        bRef = bool(self.getValue('Use channel B as reference signal'))

        # calculate cos/sin vectors, allow segmenting
        if not hasattr(self, '_dt') or dt != self._dt or \
                not hasattr(self, '_skipIndex') or \
                skipIndex != self._skipIndex or \
                not hasattr(self, '_length') or \
                length != self._length or \
                not hasattr(self, '_dFreq') or \
                dFreq != self._dFreq:
            vTime = dt * (skipIndex + np.arange(length, dtype=np.float32))
            self._vExp = np.exp(2.j * np.pi * vTime * dFreq)
            self._dt = dt
            self._skipIndex = skipIndex
            self._length = length
            self._dFreq = dFreq
        vExp = self._vExp

        # calc I/Q
        if not hasattr(self, '_nSegment') or nSegment != self._nSegment:
            self._signal = np.empty(nSegment, dtype=np.complex64)
            if bRef:
                self._ref = np.empty(nSegment, dtype=np.complex64)
            self._nSegment = nSegment
        signal = self._signal
        np.dot(vData[:,skipIndex:skipIndex+length], vExp, signal)
        signal /= .5 * float(length)

        if bRef:
            try:
                vRef = self.data['Channel B - Flattened data']
            except KeyError:
                raise KeyError("Select 'Channel B - Enabled' to "
                        "acquire the reference data.")
            ref = self._ref
            np.dot(vRef[:,skipIndex:skipIndex+length], vExp, ref)
            # subtract the reference angle
            expRef = np.exp(-1j * np.angle(ref))
            signal *= expRef

        self.data[sSingleShot] = signal
        self.data[sValue] = np.mean(signal)
        
        if bRef:
            if not hasattr(self, '_segmentLength') or \
                segmentLength != self._segmentLength:
                self._timeAverage = np.empty(segmentLength, dtype=np.complex64)
                self._segmentLength = segmentLength
            timeAverage = self._timeAverage
            np.dot(vData.T, np.conj(expRef), timeAverage)
        else:
            timeAverage = np.sum(vData, 0)
        timeAverage /= nSegment
        self.data[sTimeAverage] = timeAverage

if __name__ == '__main__':
    pass