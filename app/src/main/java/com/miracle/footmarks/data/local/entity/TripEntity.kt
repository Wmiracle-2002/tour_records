package com.miracle.footmarks.data.local.entity

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "trips",
    foreignKeys = [
        ForeignKey(
            entity = CityEntity::class,
            parentColumns = ["id"],
            childColumns = ["cityId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("cityId"), Index("startDate")]
)
data class TripEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val cityId: Long,
    val startDate: Long,
    val endDate: Long,
    val createdAt: Long = System.currentTimeMillis()
)
