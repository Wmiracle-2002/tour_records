package com.miracle.footmarks.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.navArgument
import com.miracle.footmarks.R
import com.miracle.footmarks.ui.screen.addrecord.AddRecordScreen
import com.miracle.footmarks.ui.screen.editrecord.EditRecordScreen
import com.miracle.footmarks.ui.screen.profile.ProfileScreen
import com.miracle.footmarks.ui.screen.recorddetail.RecordDetailScreen
import com.miracle.footmarks.ui.screen.records.RecordsScreen
import com.miracle.footmarks.ui.screen.smartplanning.SmartPlanningScreen

data class BottomNavItem(
    val route: String,
    val icon: ImageVector,
    val label: Int
)

val bottomNavItems = listOf(
    BottomNavItem(Screen.Records.route, Icons.Default.DateRange, R.string.nav_records),
    BottomNavItem(Screen.SmartPlanning.route, Icons.Default.Star, R.string.nav_smart_planning),
    BottomNavItem(Screen.Profile.route, Icons.Default.Person, R.string.nav_profile)
)

@Composable
fun MainBottomBar(
    navController: NavHostController,
    modifier: Modifier = Modifier
) {
    NavigationBar(modifier = modifier) {
        val navBackStackEntry by navController.currentBackStackEntryAsState()
        val currentDestination = navBackStackEntry?.destination

        bottomNavItems.forEach { item ->
            NavigationBarItem(
                icon = { Icon(item.icon, contentDescription = null) },
                label = { Text(stringResource(item.label)) },
                selected = currentDestination?.hierarchy?.any { it.route == item.route } == true,
                onClick = {
                    navController.navigate(item.route) {
                        popUpTo(navController.graph.findStartDestination().id) {
                            saveState = true
                        }
                        launchSingleTop = true
                        restoreState = true
                    }
                }
            )
        }
    }
}

@Composable
fun MainNavHost(
    navController: NavHostController,
    modifier: Modifier = Modifier
) {
    NavHost(
        navController = navController,
        startDestination = Screen.Records.route,
        modifier = modifier
    ) {
        composable(Screen.Records.route) {
            RecordsScreen(
                onRecordClick = { recordId ->
                    navController.navigate(Screen.RecordDetail.createRoute(recordId))
                },
                onAddClick = {
                    navController.navigate(Screen.AddRecord.route)
                }
            )
        }

        composable(Screen.SmartPlanning.route) {
            SmartPlanningScreen()
        }

        composable(Screen.Profile.route) {
            ProfileScreen()
        }

        composable(Screen.AddRecord.route) {
            AddRecordScreen(
                onSaved = {
                    navController.popBackStack()
                },
                onCancel = {
                    navController.popBackStack()
                }
            )
        }

        composable(
            route = Screen.EditRecord.route,
            arguments = listOf(navArgument("recordId") { type = NavType.LongType })
        ) {
            EditRecordScreen(
                onSaved = {
                    navController.popBackStack()
                },
                onCancel = {
                    navController.popBackStack()
                }
            )
        }

        composable(
            route = Screen.RecordDetail.route,
            arguments = listOf(navArgument("recordId") { type = NavType.LongType })
        ) {
            RecordDetailScreen(
                onBack = { navController.popBackStack() },
                onEdit = { recordId ->
                    navController.navigate(Screen.EditRecord.createRoute(recordId))
                }
            )
        }

        composable(
            route = Screen.CityDetail.route,
            arguments = listOf(navArgument("cityId") { type = NavType.LongType })
        ) {
            // CityDetailScreen - 后续实现
            Text("城市详情")
        }
    }
}
