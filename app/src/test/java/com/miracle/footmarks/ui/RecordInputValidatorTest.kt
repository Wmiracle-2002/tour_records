package com.miracle.footmarks.ui

import com.miracle.footmarks.ui.validation.RecordInputValidator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RecordInputValidatorTest {
    @Test
    fun validOptionalFieldsCanBeEmpty() {
        assertNull(
            RecordInputValidator.validate(
                cityId = 1,
                name = "故宫",
                cost = null,
                notes = "",
                photoCount = 0
            )
        )
    }

    @Test
    fun requiredAndBoundaryErrorsAreReported() {
        assertEquals("请选择城市", validate(cityId = null))
        assertEquals("请输入名称", validate(name = "  "))
        assertEquals("名称不能超过100个字符", validate(name = "景".repeat(101)))
        assertEquals("花费不能小于0元", validate(cost = -1f))
        assertEquals("花费不能超过10000000元", validate(cost = 10_000_001f))
        assertEquals("备注不能超过2000个字符", validate(notes = "记".repeat(2001)))
        assertEquals("每条记录最多选择9张照片", validate(photoCount = 10))
    }

    private fun validate(
        cityId: Long? = 1,
        name: String = "故宫",
        cost: Float? = null,
        notes: String = "",
        photoCount: Int = 0
    ) = RecordInputValidator.validate(cityId, name, cost, notes, photoCount)
}
