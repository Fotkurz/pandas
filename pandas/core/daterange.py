# pylint: disable-msg=E1101,E1103

from datetime import datetime
import operator

import numpy as np

from pandas.core.index import Index
import pandas.core.datetools as datetools

#-------------------------------------------------------------------------------
# XDateRange class

class XDateRange(object):
    """
    XDateRange generates a sequence of dates corresponding to the
    specified time offset

    Note
    ----
    If both fromDate and toDate are specified, the returned dates will
    satisfy:

    fromDate <= date <= toDate

    In other words, dates are constrained to lie in the specifed range
    as you would expect, though no dates which do NOT lie on the
    offset will be returned.

    XDateRange is a generator, use if you do not intend to reuse the
    date range, or if you are doing lazy iteration, or if the number
    of dates you are generating is very large. If you intend to reuse
    the range, use DateRange, which will be the list of dates
    generated by XDateRange.

    See also
    --------
    DateRange
    """
    _cache = {}
    _cacheStart = {}
    _cacheEnd = {}
    def __init__(self, fromDate=None, toDate=None, nPeriods=None,
                 offset=datetools.BDay(), timeRule=None):

        if timeRule is not None:
            offset = datetools.getOffset(timeRule)

        if timeRule is None:
            if offset in datetools._offsetNames:
                timeRule = datetools._offsetNames[offset]

        fromDate = datetools.to_datetime(fromDate)
        toDate = datetools.to_datetime(toDate)

        if fromDate and not offset.onOffset(fromDate):
            fromDate = fromDate + offset.__class__(n=1, **offset.kwds)
        if toDate and not offset.onOffset(toDate):
            toDate = toDate - offset.__class__(n=1, **offset.kwds)
            if nPeriods == None and toDate < fromDate:
                toDate = None
                nPeriods = 0

        if toDate is None:
            toDate = fromDate + (nPeriods - 1) * offset

        if fromDate is None:
            fromDate = toDate - (nPeriods - 1) * offset

        self.offset = offset
        self.timeRule = timeRule
        self.fromDate = fromDate
        self.toDate = toDate
        self.nPeriods = nPeriods

    def __iter__(self):
        offset = self.offset
        cur = self.fromDate
        if offset._normalizeFirst:
            cur = datetools.normalize_date(cur)
        while cur <= self.toDate:
            yield cur
            cur = cur + offset

#-------------------------------------------------------------------------------
# DateRange cache

CACHE_START = datetime(1950, 1, 1)
CACHE_END   = datetime(2030, 1, 1)

#-------------------------------------------------------------------------------
# DateRange class

def _bin_op(op):
    def f(self, other):
        return op(self.view(np.ndarray), other)

    return f

class DateRange(Index):
    """
    Fixed frequency date range according to input parameters.

    Input dates satisfy:
        begin <= d <= end, where d lies on the given offset

    Parameters
    ----------
    fromDate : {datetime, None}
        left boundary for range
    toDate : {datetime, None}
        right boundary for range
    periods : int
        Number of periods to generate.
    offset : DateOffset, default is 1 BusinessDay
        Used to determine the dates returned
    timeRule : timeRule to use
    """
    _cache = {}
    _parent = None
    def __new__(cls, fromDate=None, toDate=None, periods=None,
                offset=datetools.bday, timeRule=None, **kwds):

        # Allow us to circumvent hitting the cache
        index = kwds.get('index')
        if index is None:
            # Cachable
            if not fromDate:
                fromDate = kwds.get('begin')
            if not toDate:
                toDate = kwds.get('end')
            if not periods:
                periods = kwds.get('nPeriods')

            fromDate = datetools.to_datetime(fromDate)
            toDate = datetools.to_datetime(toDate)

            # inside cache range
            fromInside = fromDate is not None and fromDate > CACHE_START
            toInside = toDate is not None and toDate < CACHE_END

            useCache = fromInside and toInside

            if (useCache and offset.isAnchored() and
                not isinstance(offset, datetools.Tick)):

                index = cls.getCachedRange(fromDate, toDate, periods=periods,
                                           offset=offset, timeRule=timeRule)

            else:
                xdr = XDateRange(fromDate=fromDate, toDate=toDate,
                                 nPeriods=periods, offset=offset,
                                 timeRule=timeRule)

                index = np.array(list(xdr), dtype=object, copy=False)

                index = index.view(cls)
                index.offset = offset
        else:
            index = index.view(cls)

        return index


    @property
    def _allDates(self):
        return True

    @classmethod
    def getCachedRange(cls, start=None, end=None, periods=None, offset=None,
                       timeRule=None):

        # HACK: fix this dependency later
        if timeRule is not None:
            offset = datetools.getOffset(timeRule)

        if offset is None:
            raise Exception('Must provide a DateOffset!')

        if offset not in cls._cache:
            xdr = XDateRange(CACHE_START, CACHE_END, offset=offset)
            arr = np.array(list(xdr), dtype=object, copy=False)

            cachedRange = DateRange.fromIndex(arr)
            cachedRange.offset = offset

            cls._cache[offset] = cachedRange
        else:
            cachedRange = cls._cache[offset]

        if start is None:
            if end is None:
                raise Exception('Must provide start or end date!')
            if periods is None:
                raise Exception('Must provide number of periods!')

            assert(isinstance(end, datetime))

            end = offset.rollback(end)

            endLoc = cachedRange.indexMap[end] + 1
            startLoc = endLoc - periods
        elif end is None:
            assert(isinstance(start, datetime))
            start = offset.rollforward(start)

            startLoc = cachedRange.indexMap[start]
            if periods is None:
                raise Exception('Must provide number of periods!')

            endLoc = startLoc + periods
        else:
            start = offset.rollforward(start)
            end = offset.rollback(end)

            startLoc = cachedRange.indexMap[start]
            endLoc = cachedRange.indexMap[end] + 1

        indexSlice = cachedRange[startLoc:endLoc]
        indexSlice._parent = cachedRange

        return indexSlice

    @classmethod
    def fromIndex(cls, index):
        index = cls(index=index)
        return index

    def __array_finalize__(self, obj):
        if self.ndim == 0: # pragma: no cover
            return self.item()

        self.offset = getattr(obj, 'offset', None)
        self._parent = getattr(obj, '_parent',  None)

    __lt__ = _bin_op(operator.lt)
    __le__ = _bin_op(operator.le)
    __gt__ = _bin_op(operator.gt)
    __ge__ = _bin_op(operator.ge)
    __eq__ = _bin_op(operator.eq)

    def __getslice__(self, i, j):
        return self.__getitem__(slice(i, j))

    def __getitem__(self, key):
        """Override numpy.ndarray's __getitem__ method to work as desired"""
        result = self.view(np.ndarray)[key]

        if isinstance(key, (int, np.int32)):
            return result
        elif isinstance(key, slice):
            newIndex = result.view(DateRange)

            if key.step is not None:
                newIndex.offset = key.step * self.offset
            else:
                newIndex.offset = self.offset

            return newIndex
        else:
            return Index(result)

    def __repr__(self):
        output = str(self.__class__) + '\n'
        output += 'offset: %s\n' % self.offset
        output += '[%s, ..., %s]\n' % (self[0], self[-1])
        output += 'length: %d' % len(self)
        return output

    __str__ = __repr__

    def shift(self, n):
        if n > 0:
            start = self[-1] + self.offset
            tail = DateRange(fromDate=start, periods=n)
            newArr = np.concatenate((self[n:], tail)).view(DateRange)
            newArr.offset = self.offset
            return newArr
        elif n < 0:
            end = self[0] - self.offset
            head = DateRange(toDate=end, periods=-n)

            newArr = np.concatenate((head, self[:n])).view(DateRange)
            newArr.offset = self.offset
            return newArr
        else:
            return self
