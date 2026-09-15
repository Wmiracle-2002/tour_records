package com.miracle.footmarks.ui

import com.miracle.footmarks.ui.validation.TripDateValidator
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TripDateValidatorTest {
    private val start = LocalDate.of(2026, 9, 10)
    private val end = LocalDate.of(2026, 9, 15)

    @Test
    fun acceptsRecordDateInsideInclusiveTripRange() {
        assertNull(TripDateValidator.validate(start, end, start))
        assertNull(TripDateValidator.validate(start, end, end))
    }

    @Test
    fun rejectsInvalidTripRangeAndOutsideRecordDate() {
        assertEquals("结束日期不能早于开始日期", TripDateValidator.validate(end, start, end))
        assertEquals(
            "记录日期必须在旅行日期范围内",
            TripDateValidator.validate(start, end, end.plusDays(1))
        )
    }
}
