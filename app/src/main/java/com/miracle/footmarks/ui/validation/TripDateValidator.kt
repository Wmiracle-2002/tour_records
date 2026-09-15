package com.miracle.footmarks.ui.validation

import java.time.LocalDate

object TripDateValidator {
    fun validate(startDate: LocalDate, endDate: LocalDate, recordDate: LocalDate): String? = when {
        endDate.isBefore(startDate) -> "结束日期不能早于开始日期"
        recordDate !in startDate..endDate -> "记录日期必须在旅行日期范围内"
        else -> null
    }
}
