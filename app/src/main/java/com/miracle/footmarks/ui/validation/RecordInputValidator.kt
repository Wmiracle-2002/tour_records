package com.miracle.footmarks.ui.validation

object RecordInputValidator {
    const val MAX_NAME_LENGTH = 100
    const val MAX_NOTES_LENGTH = 2_000
    const val MAX_PHOTO_COUNT = 9
    const val MAX_COST = 10_000_000f

    fun validate(
        cityId: Long?,
        name: String,
        cost: Float?,
        notes: String,
        photoCount: Int
    ): String? = when {
        cityId == null -> "请选择城市"
        name.isBlank() -> "请输入名称"
        name.length > MAX_NAME_LENGTH -> "名称不能超过100个字符"
        cost != null && cost < 0f -> "花费不能小于0元"
        cost != null && cost > MAX_COST -> "花费不能超过10000000元"
        notes.length > MAX_NOTES_LENGTH -> "备注不能超过2000个字符"
        photoCount > MAX_PHOTO_COUNT -> "每条记录最多选择9张照片"
        else -> null
    }
}
