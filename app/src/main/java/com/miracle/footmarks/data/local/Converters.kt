package com.miracle.footmarks.data.local

import androidx.room.TypeConverter
import com.miracle.footmarks.data.local.entity.RecordType

class Converters {
    @TypeConverter
    fun fromRecordType(value: RecordType): String {
        return value.name
    }

    @TypeConverter
    fun toRecordType(value: String): RecordType {
        return RecordType.valueOf(value)
    }
}
