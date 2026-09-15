package com.miracle.footmarks.data.local.entity

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "records",
    foreignKeys = [
        ForeignKey(
            entity = TripEntity::class,
            parentColumns = ["id"],
            childColumns = ["tripId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("tripId"), Index("date")]
)
data class RecordEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val tripId: Long,
    val type: RecordType,
    val name: String,
    val date: Long, // 时间戳（毫秒）
    val rating: Float? = null, // 1-5星，可选
    val cost: Float? = null, // 花费（元），可选
    val notes: String? = null,
    val photoUris: String? = null, // 多张照片路径，逗号分隔
    val createdAt: Long = System.currentTimeMillis()
)

enum class RecordType {
    ATTRACTION, // 景点
    FOOD // 美食
}
