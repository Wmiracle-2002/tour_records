package com.miracle.footmarks.ui.navigation

sealed class Screen(val route: String) {
    object Records : Screen("records")
    object SmartPlanning : Screen("smart_planning")
    object Profile : Screen("profile")
    object AddRecord : Screen("add_record")
    object EditRecord : Screen("edit_record/{recordId}") {
        fun createRoute(recordId: Long) = "edit_record/$recordId"
    }
    object RecordDetail : Screen("record_detail/{recordId}") {
        fun createRoute(recordId: Long) = "record_detail/$recordId"
    }
    object CityDetail : Screen("city_detail/{cityId}") {
        fun createRoute(cityId: Long) = "city_detail/$cityId"
    }
}
