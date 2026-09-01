"""Constants for the HA SQL PV Forecast integration."""
from __future__ import annotations

DOMAIN = "pv_history_forecast"

# Configuration keys
CONF_DB_URL = "db_url"
CONF_SENSOR_PREFIX = "sensor_prefix"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_SENSOR_CLOUDS = "sensor_clouds"
CONF_SENSOR_PV = "sensor_pv"
CONF_SENSOR_FORECAST = "sensor_forecast"
CONF_PV_HISTORY_DAYS = "pv_history_days"
CONF_SENSOR_UV = "sensor_uv"
CONF_SENSOR_TEMP = "sensor_temp"
CONF_SENSOR_PRECIP = "sensor_precip"
CONF_LOVELACE_SENSOR = "lovelace_sensor"
CONF_PV_MAX_RECORD = "pv_max_record"
CONF_RETUNE = "retune"

# Advanced options
CONF_VALUE_TEMPLATE = "value_template"
CONF_UNIT_OF_MEASUREMENT = "unit_of_measurement"
CONF_DEVICE_CLASS = "device_class"
CONF_STATE_CLASS = "state_class"

# Defaults
DEFAULT_SENSOR_PREFIX = "pv_hist"
HELP_URL = "https://www.libe.net/en/pv-forecast"

PREP_AND_POOL_BUILDING = """{% set raw = value if value is defined and value is not none else raw_json %}
{% if raw and raw != '[]' and raw is not none %}
  {% set data = raw | from_json %}
  {% set p = retune_params if retune_params is mapping else dict() %}
  {% set display_top_n = p.top_n | default(15) | int %}
  {% set uv_weight = p.uv_weight | default(1.0) | float %}
  {% set temp_weight = p.temp_weight | default(0.08) | float %}
  {% set precip_weight = p.precip_weight | default(0.03) | float %}
  {% set temp_coeff = p.temp_coeff | default(-0.003) | float %}
  {% set recency_amp = p.recency_amp | default(0.30) | float %}
  {% set season_exponent = p.season_exponent | default(1.0) | float %}
  {% set doy_weight = p.doy_weight | default(0.05) | float %}
  {% set pv_max_record = p.pv_max | default(100.0) | float %}
  {% set pv_act = data.pv_activity if data.pv_activity is mapping else data.pv_activity | from_json %}
  {% set fc = data.forecast if data.forecast is mapping else data.forecast | from_json %}
  {% set latitude = state_attr('zone.home', 'latitude') | float(default=52.52) %}
  {% set local_latitude = latitude %}

  {% set pi = 3.141592653589793 %}
  {% set sun_end_local = pv_act.sun_end_local | default('18:30') %}
  {% set end_min_local = ((sun_end_local.split(':')[0] | int) * 60 + (sun_end_local.split(':')[1] | int)) %}

  {% if (now().hour * 60 + now().minute) > end_min_local %}
    0.0
  {% else %}
    {% set cloud_ready = fc.remaining is defined and fc.remaining is not none %}
    {% if not cloud_ready %}
      {{ none }}
    {% else %}
      {% set f_avg = fc.remaining.cloud | float(default=50.0) %}
      {% set f_uv_avg = fc.remaining.uv | float(default=0.0) %}
      {% set f_temp_avg = fc.remaining.temp | float(default=15.0) %}
      {% set f_precip_avg = fc.remaining.precip | float(default=0.0) %}
      {% set current_month = now().month %}

      {# --- SEASONAL SNOW DETECTION --- #}
      {% set snow_factor_today = namespace(val=1.0) %}
      {% if current_month in [12, 1, 2] %}
        {% set yesterday_date = (now() - timedelta(days=1)).strftime('%Y-%m-%d') %}
        {% set summary_list_snow = data.daily_summary if data.daily_summary is iterable and data.daily_summary is not string else data.daily_summary | from_json %}
        {% set yesterday_data = summary_list_snow | selectattr('day', 'equalto', yesterday_date) | list | first %}
        {% if yesterday_data is defined %}
          {% set yesterday_valid = yesterday_data if yesterday_data is mapping else yesterday_data | from_json %}
          {% set yesterday_yield = yesterday_valid.remaining.pv_yield | float(default=0) %}
          {% set yesterday_h_avg = yesterday_valid.remaining.cloud | float(default=0) %}
          {% set yesterday_perf = yesterday_yield / ([105 - yesterday_h_avg, 5] | max) %}
          {% if yesterday_perf < 0.02 %}
            {% set snow_factor_today.val = 0.1 %}
          {% endif %}
        {% endif %}
      {% endif %}

      {# --- ASTRONOMICAL BASE DATA FOR TODAY --- #}
      {% set doy = now().strftime('%j') | int(default=1) %}
      {% set lat_rad = latitude * pi / 180 %}
      {% set dec_ang = (2 * pi * (doy + 10) / 365) %}
      {% set dec_ang_norm = dec_ang - (2 * pi * (dec_ang / (2 * pi)) | int) %}
      {% set cos_dec = 1.0 - (dec_ang_norm**2 / 2.0) + (dec_ang_norm**4 / 24.0) - (dec_ang_norm**6 / 720.0) %}
      {% set decl = -0.4093 * cos_dec %}
      {% set doy_ang = ((doy - 172) * 2 * pi / 365) %}
      {% set doy_ang_norm = doy_ang - (2 * pi * (doy_ang / (2 * pi)) | int) %}
      {% set cos_doy = 1.0 - (doy_ang_norm**2 / 2.0) + (doy_ang_norm**4 / 24.0) - (doy_ang_norm**6 / 720.0) %}
      {% set dl_today = 12.0 + 4.0 * (latitude / 50.0) * cos_doy %}

      {% set ns_pool = namespace(items=[]) %}
      {% set summary_list = data.daily_summary if data.daily_summary is iterable and data.daily_summary is not string else data.daily_summary | from_json %}

      {# --- BUILD DATA POOL VIA REMAINING METRICS --- #}
      {% for item in summary_list %}
        {% set item_valid = item if item is mapping else item | from_json %}
        {% set yield_raw = item_valid.remaining.pv_yield | float(default=0.0) %}

        {# Schwellenwert auf > 0.05 angehoben #}
        {% if yield_raw > 0.05 %}
          {% set clouds = item_valid.remaining.cloud | float(default=0.0) %}
          {% set uv_hist = item_valid.remaining.uv | float(default=0.0) %}
          {% set temp_hist = item_valid.remaining.temp | float(default=15.0) %}
          {% set precip = item_valid.remaining.precip | float(default=0.0) %}
          {% set yield_total_day = item_valid.total.pv_yield | float(default=0.0) %}
          {% set dt_item = as_datetime(item_valid.day) %}

          {% if dt_item is not none %}
            {% set item_day = dt_item.strftime('%j') | int(default=1) %}
            {% set item_doy_ang = ((item_day - 172) * 2 * pi / 365) %}
            {% set item_doy_norm = item_doy_ang - (2 * pi * (item_doy_ang / (2 * pi)) | int) %}
            {% set cos_doy_i = 1.0 - (item_doy_norm**2 / 2.0) + (item_doy_norm**4 / 24.0) - (item_doy_norm**6 / 720.0) %}
            {% set dl_item = 12.0 + 4.0 * (latitude / 50.0) * cos_doy_i %}

            {# Correction only via day-length ratio (prevents double compensation) #}
            {% set s_korr = (dl_today / dl_item) if dl_item > 0 else 1.0 %}
            {% set s_korr = [s_korr, 1.35] | min %}
            {% set yield_korr = yield_raw * s_korr %}
            {% set yield_total_day_korr = yield_total_day * s_korr %}

            {# Physikalisch korrekte Temperatur-Differenz: (Historisch - Ziel) * Koeffizient #}
            {% set temp_factor = [[1.0 + (( f_temp_avg - temp_hist ) * temp_coeff), 0.85] | max, 1.15] | min %}
            {% set yield_korr = yield_korr * temp_factor %}
            {% set yield_total_day_korr = yield_total_day_korr * temp_factor %}

            {# Proportional capping at the end of the chain using the daily average #}
            {% if pv_max_record > 0 and yield_total_day_korr > pv_max_record %}
              {% set capped_factor = pv_max_record / yield_total_day_korr %}
              {% set yield_korr = yield_korr * capped_factor %}
            {% endif %}

            {# ERROR-DIFFERENCE CALCULATION #}
            {% set diff_c = (clouds - f_avg) | abs %}
            {% if f_uv_avg > 0 %}
              {% set uv_w = [0.3 + 0.4 * (f_avg / 100.0), 0.7] | min %}
              {% set diff = diff_c * (1.0 - uv_w) + (uv_hist - f_uv_avg) | abs * 6.0 * uv_w * uv_weight %}
            {% else %}
              {% set diff = diff_c %}
            {% endif %}
            {% set diff = diff + ((f_temp_avg - temp_hist) | abs * temp_weight) %}
            {% set diff = diff + ((precip - f_precip_avg) | abs * precip_weight) %}

            {# Seasonal penalty (circular day-of-year calculation) #}
            {% set doy_diff = (doy - item_day) | abs %}
            {% set doy_diff = (365.0 - doy_diff) if doy_diff > 182.5 else doy_diff %}
            {% set diff = diff + (doy_diff  * doy_weight) %}

            {% set days_ago = ((now().timestamp() - dt_item.timestamp()) / 86400) | int(0) %}

            {# Denominator floor lowered from 1.0 to 0.1 for stronger prioritization of near-perfect days #}
            {% set w = (1 / ([diff * 0.5, 0.1] | max)) * (1.0 + recency_amp * ([1.0 - days_ago / 30.0, 0.0] | max)) %}
            {% set ns_pool.items = ns_pool.items + [{'day': item_valid.day, 'cloud': clouds, 'uv': uv_hist, 'temp': temp_hist, 'precip': precip,'temp_factor' : temp_factor, 's_korr': s_korr, 'yield': yield_korr, 'w': w, 'diff': diff, 'days_ago': days_ago}] %}
          {% endif %}
        {% endif %}
      {% endfor %}

      {% set pool = (ns_pool.items | sort(attribute='w', reverse=True))[:display_top_n] %}
      {% set global_trend_factor = namespace(val=1.0) %}
      {% set global_loo_factor = namespace(val=1.0) %}
      {% set ns_cv = namespace(items=[]) %}

      {# CALCULATE UNCORRECTED HISTORICAL MEAN #}
      {% set ns_init_def = namespace(w=0, wy=0) %}
      {% for item in pool %}{% set ns_init_def.w = ns_init_def.w + item.w %}{% set ns_init_def.wy = ns_init_def.wy + (item.yield * item.w) %}{% endfor %}
      {% set base_historical_yield = (ns_init_def.wy / ns_init_def.w if ns_init_def.w > 0 else 0.0) %}

      {# WEATHER-ONLY FALLBACK WHEN NO HISTORICAL POOL EXISTS.
         This keeps the sensor responsive for new installs or providers like met.no
         even before enough historical comparison days are available. #}
      {% set weather_fallback_yield = namespace(val=0.0) %}
      {% if pool | count == 0 %}
        {% set weather_fallback_yield.val = ([1.0 - (f_avg / 100.0), 0.0] | max) * 3.0 + ([f_uv_avg / 10.0, 0.0] | max) + ([f_temp_avg - 15.0, 0.0] | max) * 0.08 %}
        {% if pv_max_record > 0 and weather_fallback_yield.val > pv_max_record %}
          {% set weather_fallback_yield.val = pv_max_record %}
        {% endif %}
      {% endif %}

      {# GLOBAL FINAL CORRECTION FOR THE EXPECTED SENSOR VALUE (DEFAULT) #}
      {% set global_base_yield = (base_historical_yield if pool | count > 0 else weather_fallback_yield.val) * global_loo_factor.val * global_trend_factor.val %}

      {# PROVIDE GLOBAL POOL METRICS FOR MIN / MAX #}
      {% set ns_global_mean = namespace(sum=0.0, count=0) %}
      {% for item in pool %}{% if item.yield > 0 %}{% set ns_global_mean.sum = ns_global_mean.sum + item.yield %}{% set ns_global_mean.count = ns_global_mean.count + 1 %}{% endif %}{% endfor %}
      {% set mean_pool_yield = ns_global_mean.sum / ([ns_global_mean.count, 1] | max) %}"""

DEFAULT_VALUE_TEMPLATE = PREP_AND_POOL_BUILDING + """
      {# MODULE 2A: DEFAULT SENSOR BACKEND #}
      {% set res_val = global_base_yield %}

      {# --- YESTERDAY PENALTY --- #}
      {% set ns_all = namespace(sum_y=0.0, count_y=0) %}
      {% for item in pool %}{% if item.yield > 0 %}{% set ns_all.sum_y = ns_all.sum_y + item.yield %}{% set ns_all.count_y = ns_all.count_y + 1 %}{% endif %}{% endfor %}
      {% set mean_y = ns_all.sum_y / ([ns_all.count_y, 1] | max) %}
      {% set ns_bt = namespace(total=0, useful=0, trigger_sum=0.0, carry_sum=0.0) %}
      {% for item_i in pool %}
        {% if item_i.yield >= 0.05 * mean_y and item_i.yield < 0.85 * mean_y %}
          {% set next_date  = (as_datetime(item_i.day) + timedelta(days=1)).strftime('%Y-%m-%d') %}
          {% set next_items = pool | selectattr('day', 'equalto', next_date) | list %}
          {% if next_items | length > 0 %}
            {% set item_j            = next_items[0] %}
            {% set ns_bt.total       = ns_bt.total + 1 %}
            {% set ns_bt.trigger_sum = ns_bt.trigger_sum + (1.0 - item_i.yield / mean_y) %}
            {% set ns_bt.carry_sum   = ns_bt.carry_sum   + ([1.0 - item_j.yield / mean_y, 0.0] | max) %}
            {% if item_j.yield < mean_y %}{% set ns_bt.useful = ns_bt.useful + 1 %}{% endif %}
          {% endif %}
        {% endif %}
      {% endfor %}
      {% set effective_carry = (ns_bt.carry_sum / ns_bt.trigger_sum) * (ns_bt.useful / ns_bt.total) if (ns_bt.total > 0 and ns_bt.trigger_sum > 0) else 0.3 %}

      {% set yesterday_date_yp = (now() - timedelta(days=1)).strftime('%Y-%m-%d') %}
      {% set yest_cv   = ns_cv.items | selectattr('day', 'equalto', yesterday_date_yp) | list if ns_cv is defined else [] %}
      {% set yest_item = pool | selectattr('day', 'equalto', yesterday_date_yp) | list %}
      {% set yest_clouds = yest_item[0].cloud if yest_item | length > 0 else 0 %}
      {% if yest_cv | length > 0 %}
        {% set yest_cv_item = yest_cv[0] %}
        {% if yest_cv_item.acc >= 40 and yest_cv_item.acc < 85 and f_avg >= 60 and yest_clouds >= 60 %}
          {% set res_val = res_val * ([1.0 - effective_carry * (1.0 - yest_cv_item.acc / 100.0), 0.5] | max) %}
        {% endif %}
      {% endif %}

      {% set live_hour_delta = data.live_hour_delta | default(0.0) | float %}
      {% set estimated_rest = (res_val * snow_factor_today.val) | float %}
      {% set remaining_live = estimated_rest - live_hour_delta %}
      {% set current_minutes = (now().hour * 60 + now().minute) | int %}
      {% set minutes_to_sunset = (end_min_local - current_minutes) | int %}
      {% set live_floor = (0.8 * estimated_rest * (minutes_to_sunset - now().minute)) / ([minutes_to_sunset, 1] | max) %}
      {% if minutes_to_sunset <= 0 %}
        {% set final_val = 0.0 %}
      {% else %}
        {% set final_val = [remaining_live, live_floor, 0.0] | max %}
      {% endif %}
      {{ [final_val, 0.0] | max | round(2) }}
    {% endif %}
  {% endif %}
{% else %}
  0.0
{% endif %}"""

DEFAULT_VALUE_TEMPLATE_MIN = PREP_AND_POOL_BUILDING + """
      {# MODULE 2B: PESSIMISTIC MINIMUM BACKEND #}
      {# CLOUD FILTERS BASED ON THE SYNCHRONIZED MAIN POOL #}
      {% set brighter = pool | selectattr('cloud', 'le', f_avg) | list %}
      {% set darker = pool | selectattr('cloud', 'gt', f_avg) | list %}

      {% set base_min = namespace(val=0.0) %}
      {% if pool | count > 0 %}
        {% if brighter | count > 0 and darker | count == 0 %}
          {% set worst = brighter | sort(attribute='yield') | first %}
          {% set base_min.val = worst.yield * ([120.0 - f_avg, 5.0] | max / [120.0 - worst.cloud, 5.0] | max) %}
        {% elif darker | count > 0 and brighter | count == 0 %}
          {% set base_min.val = darker | map(attribute='yield') | min %}
        {% else %}
          {% set base_min.val = pool | map(attribute='yield') | min %}
        {% endif %}
      {% endif %}

      {% set res_val = base_min.val * global_loo_factor.val * global_trend_factor.val %}

      {% set live_hour_delta = data.live_hour_delta | default(0.0) | float %}
      {% set estimated_rest = (res_val * snow_factor_today.val) | float %}
      {% set remaining_live = estimated_rest - live_hour_delta %}
      {% set current_minutes = (now().hour * 60 + now().minute) | int %}
      {% set minutes_to_sunset = (end_min_local - current_minutes) | int %}
      {% set live_floor = (0.8 * estimated_rest * (minutes_to_sunset - now().minute)) / ([minutes_to_sunset, 1] | max) %}
      {% if minutes_to_sunset <= 0 %}
        {% set final_val = 0.0 %}
      {% else %}
        {% set final_val = [remaining_live, live_floor, 0.0] | max %}
      {% endif %}
      {{ final_val | round(2) }}
    {% endif %}
  {% endif %}
{% else %}
  0.0
{% endif %}"""

DEFAULT_VALUE_TEMPLATE_MAX = PREP_AND_POOL_BUILDING + """
      {# MODULE 2C: OPTIMISTIC MAXIMUM BACKEND #}
      {# CLOUD FILTERS BASED ON THE SYNCHRONIZED MAIN POOL #}
      {% set brighter = pool | selectattr('cloud', 'le', f_avg) | list %}
      {% set darker = pool | selectattr('cloud', 'gt', f_avg) | list %}

      {% set base_max = namespace(val=0.0) %}
      {% if pool | count > 0 %}
        {% if brighter | count > 0 and darker | count == 0 %}
          {% set best = brighter | sort(attribute='yield', reverse=True) | first %}
          {% set base_max.val = best.yield * ([120.0 - f_avg, 5.0] | max / [120.0 - best.cloud, 5.0] | max) %}
        {% elif darker | count > 0 and brighter | count == 0 %}
          {% set base_max.val = darker | map(attribute='yield') | max %}
        {% else %}
          {% set base_max.val = pool | map(attribute='yield') | max %}
        {% endif %}
      {% endif %}

      {% set res_val = ([base_max.val, global_base_yield] | max) * global_loo_factor.val * global_trend_factor.val %}

      {% set live_hour_delta = data.live_hour_delta | default(0.0) | float %}
      {% set estimated_rest = (res_val * snow_factor_today.val) | float %}
      {% set remaining_live = estimated_rest - live_hour_delta %}
      {% set current_minutes = (now().hour * 60 + now().minute) | int %}
      {% set minutes_to_sunset = (end_min_local - current_minutes) | int %}
      {% set live_floor = (0.8 * estimated_rest * (minutes_to_sunset - now().minute)) / ([minutes_to_sunset, 1] | max) %}
      {% if minutes_to_sunset <= 0 %}
        {% set final_val = 0.0 %}
      {% else %}
        {% set final_val = [remaining_live, live_floor, 0.0] | max %}
      {% endif %}
      {{ final_val | round(2) }}
    {% endif %}
  {% endif %}
{% else %}
  0.0
{% endif %}"""

DEFAULT_VALUE_TEMPLATE_TOMORROW = """{# PV FORECAST TOMORROW: weighted average #}
{% set raw = value if value is defined and value is not none else raw_json %}
{% if raw and raw != '[]' and raw is not none %}
  {% set data = raw | from_json %}
  {% set p = retune_params if retune_params is mapping else dict() %}
  {% set display_top_n = p.top_n | default(15) | int %}
  {% set uv_weight = p.uv_weight | default(1.0) | float %}
  {% set temp_weight = p.temp_weight | default(0.08) | float %}
  {% set precip_weight = p.precip_weight | default(0.03) | float %}
  {% set doy_weight = p.doy_weight | default(0.05) | float %}
  {% set temp_coeff = p.temp_coeff | default(-0.003) | float %}
  {% set recency_amp = p.recency_amp | default(0.30) | float %}
  {% set season_exponent = p.season_exponent | default(1.0) | float %}

  {% set fc = data.forecast if data.forecast is mapping else data.forecast | from_json %}

  {# --- TARGETS FOR TOMORROW --- #}
  {% set f_avg_tomorrow = fc.next_day_total.cloud | float(default=50.0) %}
  {% set f_uv_avg_tomorrow = fc.next_day_total.uv | float(default=0.0) %}
  {% set f_temp_avg_tomorrow = fc.next_day_total.temp | float(default=15.0) %}
  {% set f_precip_avg_tomorrow = fc.next_day_total.precip | float(default=0.0) %}

  {% set pv_max_record = p.pv_max | default(100.0) | float %}
  {% set pi = 3.141592653589793 %}
  {% set local_latitude = state_attr('zone.home', 'latitude') | float(default=52.52) %}

  {# INITIALIZE SAFE VARIABLE FALLBACKS FOR THE LOVELACE CARD #}
  {% set trend_triggered = namespace(triggered="No") %}

  {# ASTRONOMICAL BASE DATA FOR TOMORROW #}
  {% set doy_tomorrow = (now() + timedelta(days=1)).strftime('%j') | int(default=1) %}
  {% set doy_ang = ((doy_tomorrow - 172) * 2 * pi / 365) %}
  {% set doy_ang_norm = doy_ang - (2 * pi * (doy_ang / (2 * pi)) | int) %}
  {% set cos_doy = 1.0 - (doy_ang_norm**2 / 2.0) + (doy_ang_norm**4 / 24.0) - (doy_ang_norm**6 / 720.0) %}
  {% set dl_today = 12.0 + 4.0 * (local_latitude / 50.0) * cos_doy %}

  {% set ns_pool = namespace(items=[], total_w=0) %}
  {% set summary_list = data.daily_summary if data.daily_summary is iterable and data.daily_summary is not string else data.daily_summary | from_json %}

  {# --- BUILD DATA POOL VIA TOTAL METRICS --- #}
  {% for item in summary_list %}
    {% set item_valid = item if item is mapping else item | from_json %}
    {% set yield_total = item_valid.total.pv_yield | float(default=0) %}

    {# Python equivalent: if yield_total <= 0.05: continue #}
    {% if yield_total > 0.05 %}
      {% set clouds_hist = item_valid.total.cloud | float(default=0) %}
      {% set uv_hist = item_valid.total.uv | float(default=0) %}
      {% set temp_hist = item_valid.total.temp | float(default=15.0) %}
      {% set precip_hist = item_valid.total.precip | float(default=0.0) %}
      {% set dt_item = as_datetime(item_valid.day) %}

      {% if dt_item is not none %}
        {% set item_day = dt_item.strftime('%j') | int(default=1) %}
        {% set item_doy_ang = ((item_day - 172) * 2 * pi / 365) %}
        {% set item_doy_norm = item_doy_ang - (2 * pi * (item_doy_ang / (2 * pi)) | int) %}
        {% set cos_doy_i = 1.0 - (item_doy_norm**2 / 2.0) + (item_doy_norm**4 / 24.0) - (item_doy_norm**6 / 720.0) %}

        {% set dl_item = 12.0 + 4.0 * (local_latitude / 50.0) * cos_doy_i %}

        {# Astronomical correction only via day-length ratio (prevents double compensation) #}
        {% set ratio = (dl_today / dl_item) if dl_item > 0 else 1.0 %}
        {% set s_korr = [ratio ** season_exponent, 1.35] | min %}
        {% set y_korr = yield_total * s_korr %}

        {# Physikalisch korrekte Temperatur-Differenz: (Historisch - Ziel) * Koeffizient #}
        {% set temp_factor = [[1.0 + ((f_temp_avg_tomorrow - temp_hist) * temp_coeff), 0.85] | max, 1.15] | min %}
        {% set y_korr = y_korr * temp_factor %}

        {# Proportional capping at the end of the chain #}
        {% if pv_max_record > 0 and yield_total * s_korr * temp_factor > pv_max_record %}
          {% set capped_factor = pv_max_record / (yield_total * s_korr * temp_factor) %}
          {% set y_korr = y_korr * capped_factor %}
        {% endif %}

        {# ERROR-DIFFERENCE CALCULATION #}
        {% set diff_c = (clouds_hist - f_avg_tomorrow) | abs %}
        {% if f_uv_avg_tomorrow > 0 %}
          {% set uv_w = [0.3 + 0.4 * (f_avg_tomorrow / 100.0), 0.7] | min %}
          {% set diff = diff_c * (1.0 - uv_w) + (uv_hist - f_uv_avg_tomorrow) | abs * 6.0 * uv_w * uv_weight %}
        {% else %}
          {% set diff = diff_c %}
        {% endif %}

        {% set diff = diff + ((f_temp_avg_tomorrow - temp_hist) | abs * temp_weight) %}
        {% set diff = diff + ((precip_hist - f_precip_avg_tomorrow) | abs * precip_weight) %}

        {# Seasonal penalty (circular day-of-year calculation) #}
        {% set doy_diff = (doy_tomorrow - item_day) | abs %}
        {% set doy_diff = (365.0 - doy_diff) if doy_diff > 182.5 else doy_diff %}
        {% set diff = diff + (doy_diff * doy_weight) %}


        {% set days_ago = ((now().timestamp() - dt_item.timestamp()) / 86400) | int(0) %}

        {# Denominator floor lowered from 1.0 to 0.1 for stronger prioritization of near-perfect days #}
        {% set w = (1 / ([diff * 0.5, 0.1] | max)) * (1.0 + recency_amp * ([1.0 - days_ago / 30.0, 0.0] | max)) %}

        {% set ns_pool.total_w = ns_pool.total_w + w %}
        {% set ns_pool.items = ns_pool.items + [{'day': item_valid.day, 'cloud': clouds_hist, 'uv': uv_hist, 'temp': temp_hist, 'temp_factor' : temp_factor, 'precip': precip_hist, 's_korr' : s_korr, 'w': w, 'yield': y_korr, 'diff': diff, 'days_ago': days_ago}] %}
      {% endif %}
    {% endif %}
  {% endfor %}

  {# --- 5. FORECAST CALCULATION --- #}
  {% set pool = (ns_pool.items | sort(attribute='w', reverse=True))[:display_top_n] %}
  {% set ns_top = namespace(total_w=0) %}
  {% for item in pool %}
    {% set ns_top.total_w = ns_top.total_w + item.w %}
  {% endfor %}

  {% set res = namespace(val=0.0) %}
  {% if pool | count > 0 %}
    {% set ns_mix = namespace(ws=0) %}
    {% for item in pool %}
      {% set ns_mix.ws = ns_mix.ws + (item.yield * item.w) %}
    {% endfor %}
    {% set res.val = ns_mix.ws / (ns_top.total_w if ns_top.total_w > 0 else 1) %}
  {% endif %}

  {# --- 10. FINAL VALUE OUTPUT --- #}
  {% set final_capped_val = [res.val, pv_max_record] | min if pv_max_record > 0 else res.val %}
  {{ final_capped_val | round(2) }}
{% else %}
  0.0
{% endif %}"""

DEFAULT_VALUE_TEMPLATE_DAY_AFTER_TOMORROW = """{# PV FORECAST DAY AFTER TOMORROW: weighted average #}
{% set raw = value if value is defined and value is not none else raw_json %}
{% if raw and raw != '[]' and raw is not none %}
  {% set data = raw | from_json %}
  {% set fc = data.forecast if data.forecast is mapping else data.forecast | from_json %}
  {% set day2 = fc.day2_total if fc.day2_total is mapping else dict() %}
{% endif %}
{% if raw and raw != '[]' and raw is not none and day2.cloud is defined and day2.cloud is not none %}
  {% set p = retune_params if retune_params is mapping else dict() %}
  {% set display_top_n = p.top_n | default(15) | int %}
  {% set uv_weight = p.uv_weight | default(1.0) | float %}
  {% set temp_weight = p.temp_weight | default(0.08) | float %}
  {% set precip_weight = p.precip_weight | default(0.03) | float %}
  {% set doy_weight = p.doy_weight | default(0.05) | float %}
  {% set temp_coeff = p.temp_coeff | default(-0.003) | float %}
  {% set recency_amp = p.recency_amp | default(0.30) | float %}
  {% set season_exponent = p.season_exponent | default(1.0) | float %}

  {# --- TARGETS FOR THE DAY AFTER TOMORROW --- #}
  {% set f_avg_day2 = day2.cloud | float(default=50.0) %}
  {% set f_uv_avg_day2 = day2.uv | float(default=0.0) %}
  {% set f_temp_avg_day2 = day2.temp | float(default=15.0) %}
  {% set f_precip_avg_day2 = day2.precip | float(default=0.0) %}

  {% set pv_max_record = p.pv_max | default(100.0) | float %}
  {% set pi = 3.141592653589793 %}
  {% set local_latitude = state_attr('zone.home', 'latitude') | float(default=52.52) %}

  {# ASTRONOMICAL BASE DATA FOR THE DAY AFTER TOMORROW #}
  {% set doy_day2 = (now() + timedelta(days=2)).strftime('%j') | int(default=1) %}
  {% set doy_ang = ((doy_day2 - 172) * 2 * pi / 365) %}
  {% set doy_ang_norm = doy_ang - (2 * pi * (doy_ang / (2 * pi)) | int) %}
  {% set cos_doy = 1.0 - (doy_ang_norm**2 / 2.0) + (doy_ang_norm**4 / 24.0) - (doy_ang_norm**6 / 720.0) %}
  {% set dl_today = 12.0 + 4.0 * (local_latitude / 50.0) * cos_doy %}

  {% set ns_pool = namespace(items=[], total_w=0) %}
  {% set summary_list = data.daily_summary if data.daily_summary is iterable and data.daily_summary is not string else data.daily_summary | from_json %}

  {# --- BUILD DATA POOL VIA TOTAL METRICS --- #}
  {% for item in summary_list %}
    {% set item_valid = item if item is mapping else item | from_json %}
    {% set yield_total = item_valid.total.pv_yield | float(default=0) %}

    {% if yield_total > 0.05 %}
      {% set clouds_hist = item_valid.total.cloud | float(default=0) %}
      {% set uv_hist = item_valid.total.uv | float(default=0) %}
      {% set temp_hist = item_valid.total.temp | float(default=15.0) %}
      {% set precip_hist = item_valid.total.precip | float(default=0.0) %}
      {% set dt_item = as_datetime(item_valid.day) %}

      {% if dt_item is not none %}
        {% set item_day = dt_item.strftime('%j') | int(default=1) %}
        {% set item_doy_ang = ((item_day - 172) * 2 * pi / 365) %}
        {% set item_doy_norm = item_doy_ang - (2 * pi * (item_doy_ang / (2 * pi)) | int) %}
        {% set cos_doy_i = 1.0 - (item_doy_norm**2 / 2.0) + (item_doy_norm**4 / 24.0) - (item_doy_norm**6 / 720.0) %}

        {% set dl_item = 12.0 + 4.0 * (local_latitude / 50.0) * cos_doy_i %}

        {# Astronomical correction only via day-length ratio (prevents double compensation) #}
        {% set ratio = (dl_today / dl_item) if dl_item > 0 else 1.0 %}
        {% set s_korr = [ratio ** season_exponent, 1.35] | min %}
        {% set y_korr = yield_total * s_korr %}

        {# Physikalisch korrekte Temperatur-Differenz: (Historisch - Ziel) * Koeffizient #}
        {% set temp_factor = [[1.0 + ((f_temp_avg_day2 - temp_hist) * temp_coeff), 0.85] | max, 1.15] | min %}
        {% set y_korr = y_korr * temp_factor %}

        {# Proportional capping at the end of the chain #}
        {% if pv_max_record > 0 and yield_total * s_korr * temp_factor > pv_max_record %}
          {% set capped_factor = pv_max_record / (yield_total * s_korr * temp_factor) %}
          {% set y_korr = y_korr * capped_factor %}
        {% endif %}

        {# ERROR-DIFFERENCE CALCULATION #}
        {% set diff_c = (clouds_hist - f_avg_day2) | abs %}
        {% if f_uv_avg_day2 > 0 %}
          {% set uv_w = [0.3 + 0.4 * (f_avg_day2 / 100.0), 0.7] | min %}
          {% set diff = diff_c * (1.0 - uv_w) + (uv_hist - f_uv_avg_day2) | abs * 6.0 * uv_w * uv_weight %}
        {% else %}
          {% set diff = diff_c %}
        {% endif %}

        {% set diff = diff + ((f_temp_avg_day2 - temp_hist) | abs * temp_weight) %}
        {% set diff = diff + ((precip_hist - f_precip_avg_day2) | abs * precip_weight) %}

        {# Seasonal penalty (circular day-of-year calculation) #}
        {% set doy_diff = (doy_day2 - item_day) | abs %}
        {% set doy_diff = (365.0 - doy_diff) if doy_diff > 182.5 else doy_diff %}
        {% set diff = diff + (doy_diff * doy_weight) %}

        {% set days_ago = ((now().timestamp() - dt_item.timestamp()) / 86400) | int(0) %}

        {# Denominator floor lowered from 1.0 to 0.1 for stronger prioritization of near-perfect days #}
        {% set w = (1 / ([diff * 0.5, 0.1] | max)) * (1.0 + recency_amp * ([1.0 - days_ago / 30.0, 0.0] | max)) %}

        {% set ns_pool.total_w = ns_pool.total_w + w %}
        {% set ns_pool.items = ns_pool.items + [{'day': item_valid.day, 'cloud': clouds_hist, 'uv': uv_hist, 'temp': temp_hist, 'temp_factor' : temp_factor, 'precip': precip_hist, 's_korr' : s_korr, 'w': w, 'yield': y_korr, 'diff': diff, 'days_ago': days_ago}] %}
      {% endif %}
    {% endif %}
  {% endfor %}

  {# --- FORECAST CALCULATION --- #}
  {% set pool = (ns_pool.items | sort(attribute='w', reverse=True))[:display_top_n] %}
  {% set ns_top = namespace(total_w=0) %}
  {% for item in pool %}
    {% set ns_top.total_w = ns_top.total_w + item.w %}
  {% endfor %}

  {% set res = namespace(val=0.0) %}
  {% if pool | count > 0 %}
    {% set ns_mix = namespace(ws=0) %}
    {% for item in pool %}
      {% set ns_mix.ws = ns_mix.ws + (item.yield * item.w) %}
    {% endfor %}
    {% set res.val = ns_mix.ws / (ns_top.total_w if ns_top.total_w > 0 else 1) %}
  {% endif %}

  {# --- FINAL VALUE OUTPUT --- #}
  {% set final_capped_val = [res.val, pv_max_record] | min if pv_max_record > 0 else res.val %}
  {{ final_capped_val | round(2) }}
{% else %}
  {{ none }}
{% endif %}"""

DEFAULT_UNIT_OF_MEASUREMENT = "kWh"
DEFAULT_DEVICE_CLASS = "energy"
DEFAULT_STATE_CLASS = "measurement"
DEFAULT_PV_HISTORY_DAYS = 90
DEFAULT_PV_MAX_RECORD = 0.0
DEFAULT_RETUNE = True

# Advanced SQL Query Template
DEFAULT_SQL_QUERY = """WITH vars AS (
    SELECT
        '{sensor_clouds}' as sensor_clouds,
        '{sensor_forecast}' as sensor_forecast,
        '{sensor_uv}' as sensor_uv,
        '{sensor_temp}' as sensor_temp,
        '{sensor_precip}' as sensor_precip,
        '{weather_entity}' as weather_entity,
        (strftime('%s', 'now', 'localtime') - strftime('%s', 'now')) || ' seconds' as offset,
        CAST(strftime('%s', 'now', 'localtime') - strftime('%s', 'now') AS INTEGER) as offset_seconds,
        {history_days} as history_days
),

/* Compute the history boundary once. The original predicate is
   local_date(row) > local_date(now - history_days), so the first included
   timestamp is local midnight one day after that boundary. */
clock AS (
    SELECT
        CAST(strftime(
            '%s',
            date(
                'now',
                offset,
                printf('-%d days', history_days),
                '+1 day'
            )
        ) AS INTEGER) - offset_seconds as history_start_ts
    FROM vars
),

ids AS (
    SELECT
        (SELECT id FROM statistics_meta WHERE statistic_id = (SELECT sensor_clouds FROM vars)) as cloud_id_statistics,
        (SELECT metadata_id FROM states_meta WHERE entity_id = (SELECT sensor_clouds FROM vars)) as cloud_id_states,
        (SELECT metadata_id FROM states_meta WHERE entity_id = (SELECT sensor_forecast FROM vars) LIMIT 1) as forecast_id,
        (SELECT metadata_id FROM states_meta WHERE entity_id = (SELECT weather_entity FROM vars)) as w_entity_id,
        (SELECT metadata_id FROM states_meta WHERE entity_id = 'sun.sun') as sun_id,
        (SELECT id FROM statistics_meta WHERE statistic_id = (SELECT sensor_uv FROM vars)) as uv_id_statistics,
        (SELECT metadata_id FROM states_meta WHERE entity_id = (SELECT sensor_uv FROM vars)) as uv_id_states,
        (SELECT id FROM statistics_meta WHERE statistic_id = (SELECT sensor_temp FROM vars)) as temp_id_statistics,
        (SELECT metadata_id FROM states_meta WHERE entity_id = (SELECT sensor_temp FROM vars)) as temp_id_states,
        (SELECT id FROM statistics_meta WHERE statistic_id = (SELECT sensor_precip FROM vars)) as precip_id_statistics,
        (SELECT metadata_id FROM states_meta WHERE entity_id = (SELECT sensor_precip FROM vars)) as precip_id_states
),

/* Gets all configured PV sensors including their IDs from states_meta for real-time RAM queries */
pv_stat_ids AS (
    SELECT id,
           (SELECT metadata_id FROM states_meta WHERE entity_id = statistic_id) as states_metadata_id,
           CASE WHEN unit_of_measurement = 'Wh' THEN 1000.0 ELSE 1.0 END as divisor
    FROM statistics_meta
    WHERE statistic_id IN ({sensor_pv_list})
),

pv_activity AS (
    SELECT
        COALESCE((
            SELECT strftime('%H:%M', last_updated_ts, 'unixepoch')
            FROM states
            WHERE metadata_id = (SELECT sun_id FROM ids)
              AND date(last_updated_ts, 'unixepoch', (SELECT offset FROM vars)) = date('now', (SELECT offset FROM vars), '-1 day')
              AND state = 'above_horizon'
            ORDER BY last_updated_ts ASC LIMIT 1
        ), '05:30') as sun_start,
        COALESCE((
            SELECT strftime('%H:%M', last_updated_ts, 'unixepoch')
            FROM states
            WHERE metadata_id = (SELECT sun_id FROM ids)
              AND state = 'below_horizon'
              AND last_updated_ts > (
                  SELECT last_updated_ts FROM states
                  WHERE metadata_id = (SELECT sun_id FROM ids)
                    AND date(last_updated_ts, 'unixepoch', (SELECT offset FROM vars)) = date('now', (SELECT offset FROM vars), '-1 day')
                    AND state = 'above_horizon'
                  ORDER BY last_updated_ts ASC LIMIT 1
              )
            ORDER BY last_updated_ts ASC LIMIT 1
        ), '17:30') as sun_end,
        COALESCE((
            SELECT strftime('%H:%M', last_updated_ts, 'unixepoch', (SELECT offset FROM vars))
            FROM states
            WHERE metadata_id = (SELECT sun_id FROM ids)
              AND date(last_updated_ts, 'unixepoch', (SELECT offset FROM vars)) = date('now', (SELECT offset FROM vars), '-1 day')
              AND state = 'above_horizon'
            ORDER BY last_updated_ts ASC LIMIT 1
        ), '06:30') as sun_start_local,
        COALESCE((
            SELECT strftime('%H:%M', last_updated_ts, 'unixepoch', (SELECT offset FROM vars))
            FROM states
            WHERE metadata_id = (SELECT sun_id FROM ids)
              AND state = 'below_horizon'
              AND last_updated_ts > (
                  SELECT last_updated_ts FROM states
                  WHERE metadata_id = (SELECT sun_id FROM ids)
                    AND date(last_updated_ts, 'unixepoch', (SELECT offset FROM vars)) = date('now', (SELECT offset FROM vars), '-1 day')
                    AND state = 'above_horizon'
                  ORDER BY last_updated_ts ASC LIMIT 1
              )
            ORDER BY last_updated_ts ASC LIMIT 1
        ), '18:30') as sun_end_local
    FROM ids
),

latest_forecast_ts AS (
    SELECT MAX(s.last_updated_ts) as ts
    FROM states s
    JOIN state_attributes a ON s.attributes_id = a.attributes_id
    WHERE s.metadata_id = (SELECT forecast_id FROM ids)
      AND json_extract(a.shared_attrs, '$.forecast') IS NOT NULL
      AND json_extract(a.shared_attrs, '$.forecast') != '[]'
      AND s.last_updated_ts > strftime('%s', 'now', '-6 hours')
),
pv_live_current_hour_delta AS (
    SELECT
        COALESCE(SUM(
            /* (current live state) - (counter value before the start of the current UTC hour) */
            (CAST(s_now.state AS FLOAT) - CAST(s_hour.state AS FLOAT)) / pvi.divisor
        ), 0.0) as live_hour_delta
    FROM pv_stat_ids pvi
    /* 1. Holen des aktuellen Live-Zustands im RAM (Letzter State in der Tabelle) */
    JOIN states s_now ON s_now.metadata_id = pvi.states_metadata_id
      AND s_now.state_id = (
          SELECT MAX(state_id) FROM states
          WHERE metadata_id = pvi.states_metadata_id
            AND state NOT IN ('unknown', 'unavailable', '')
      )
    /* 2. Get the real counter value from states from exactly before the start of the current hour */
    JOIN states s_hour ON s_hour.metadata_id = pvi.states_metadata_id
      AND s_hour.state_id = (
          SELECT state_id FROM states
          WHERE metadata_id = pvi.states_metadata_id
            /* MATHEMATISCHER STUNDENSCHNITT: Rundet die aktuelle Zeit auf die vollendete Stunde ab */
            AND last_updated_ts <= (strftime('%s', 'now') / 3600) * 3600
            AND state NOT IN ('unknown', 'unavailable', '')
          ORDER BY last_updated_ts DESC LIMIT 1
      )
),

weather_history_raw AS (
    SELECT (CAST(start_ts AS INT) / 3600) * 3600 as ts, CAST(COALESCE(mean, state) AS FLOAT) as cloud_val, NULL as uv_val, NULL as temp_val, NULL as precip_val
    FROM statistics
    WHERE metadata_id = (SELECT cloud_id_statistics FROM ids) AND start_ts >= (SELECT history_start_ts FROM clock)

    UNION ALL
    SELECT (CAST(s.last_updated_ts AS INT) / 3600) * 3600 as ts,
      CASE WHEN (SELECT sensor_clouds FROM vars) LIKE 'weather.%' THEN CAST(json_extract(a.shared_attrs, '$.cloud_coverage') AS FLOAT) ELSE CAST(s.state AS FLOAT) END as cloud_val,
      CASE WHEN (SELECT sensor_clouds FROM vars) LIKE 'weather.%' THEN CAST(json_extract(a.shared_attrs, '$.uv_index') AS FLOAT) ELSE NULL END as uv_val,
      NULL as temp_val, NULL as precip_val
    FROM states s
    LEFT JOIN state_attributes a ON s.attributes_id = a.attributes_id
    WHERE s.metadata_id = (SELECT cloud_id_states FROM ids)
      AND ((SELECT sensor_clouds FROM vars) LIKE 'weather.%' OR NOT EXISTS (
          SELECT 1 FROM statistics
          WHERE metadata_id = (SELECT cloud_id_statistics FROM ids)
            AND start_ts >= (CAST(s.last_updated_ts AS INT) / 3600) * 3600
            AND start_ts < ((CAST(s.last_updated_ts AS INT) / 3600) * 3600) + 3600
      ))
      AND s.last_updated_ts > strftime('%s', 'now', '-10 days')
      AND s.state NOT IN ('unknown', 'unavailable', '')

    UNION ALL
    SELECT (CAST(s.last_updated_ts AS INT) / 3600) * 3600 as ts,
        CAST(json_extract(a.shared_attrs, '$.cloud_coverage') AS FLOAT) as cloud_val, CAST(json_extract(a.shared_attrs, '$.uv_index') AS FLOAT) as uv_val,
        NULL as temp_val, CAST(json_extract(a.shared_attrs, '$.precipitation') AS FLOAT) as precip_val
    FROM states s
    LEFT JOIN state_attributes a ON s.attributes_id = a.attributes_id
    WHERE s.metadata_id = (SELECT w_entity_id FROM ids)
      AND ((SELECT sensor_clouds FROM vars) LIKE 'weather.%' OR NOT EXISTS (
          SELECT 1 FROM statistics
          WHERE metadata_id = (SELECT cloud_id_statistics FROM ids)
            AND start_ts >= CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars)
            AND start_ts < CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars) + 86400
      ))
      AND s.last_updated_ts > strftime('%s', 'now', '-10 days')
      AND json_extract(a.shared_attrs, '$.cloud_coverage') IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM statistics
          WHERE metadata_id = (SELECT cloud_id_statistics FROM ids)
            AND start_ts >= CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars)
            AND start_ts < CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars) + 86400
      )

    UNION ALL
    SELECT (CAST(start_ts AS INT) / 3600) * 3600 as ts, NULL as cloud_val, CAST(COALESCE(mean, state) AS FLOAT) as uv_val, NULL as temp_val, NULL as precip_val
    FROM statistics
    WHERE metadata_id = (SELECT uv_id_statistics FROM ids) AND start_ts >= (SELECT history_start_ts FROM clock)

    UNION ALL
    SELECT (CAST(s.last_updated_ts AS INT) / 3600) * 3600 as ts, NULL as cloud_val, CAST(s.state AS FLOAT) as uv_val, NULL as temp_val, NULL as precip_val
    FROM states s
    WHERE s.metadata_id = (SELECT uv_id_states FROM ids)
      AND NOT EXISTS (
          SELECT 1 FROM statistics
          WHERE metadata_id = (SELECT uv_id_statistics FROM ids)
            AND start_ts >= CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars)
            AND start_ts < CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars) + 86400
      )
      AND s.last_updated_ts > strftime('%s', 'now', '-10 days')
      AND s.state NOT IN ('unknown', 'unavailable', '')

    UNION ALL
    SELECT (CAST(start_ts AS INT) / 3600) * 3600 as ts, NULL as cloud_val, NULL as uv_val, CAST(COALESCE(mean, state) AS FLOAT) as temp_val, NULL as precip_val
    FROM statistics
    WHERE metadata_id = (SELECT temp_id_statistics FROM ids) AND start_ts >= (SELECT history_start_ts FROM clock)

    UNION ALL
    SELECT (CAST(s.last_updated_ts AS INT) / 3600) * 3600 as ts, NULL as cloud_val, NULL as uv_val, CAST(s.state AS FLOAT) as temp_val, NULL as precip_val
    FROM states s
    WHERE s.metadata_id = (SELECT temp_id_states FROM ids)
      AND NOT EXISTS (
          SELECT 1 FROM statistics
          WHERE metadata_id = (SELECT temp_id_statistics FROM ids)
            AND start_ts >= CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars)
            AND start_ts < CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars) + 86400
      )
      AND s.last_updated_ts > strftime('%s', 'now', '-10 days')
      AND s.state NOT IN ('unknown', 'unavailable', '')

    UNION ALL
    SELECT (CAST(start_ts AS INT) / 3600) * 3600 as ts, NULL as cloud_val, NULL as uv_val, NULL as temp_val, CAST(COALESCE(mean, state) AS FLOAT) as precip_val
    FROM statistics
    WHERE metadata_id = (SELECT precip_id_statistics FROM ids) AND start_ts >= (SELECT history_start_ts FROM clock)

    UNION ALL
    SELECT (CAST(s.last_updated_ts AS INT) / 3600) * 3600 as ts, NULL as cloud_val, NULL as uv_val, NULL as temp_val, CAST(s.state AS FLOAT) as precip_val
    FROM states s
    WHERE s.metadata_id = (SELECT precip_id_states FROM ids)
      AND NOT EXISTS (
          SELECT 1 FROM statistics
          WHERE metadata_id = (SELECT precip_id_statistics FROM ids)
            AND start_ts >= CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars)
            AND start_ts < CAST(strftime('%s', date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars))) AS INTEGER) - (SELECT offset_seconds FROM vars) + 86400
      )
      AND s.last_updated_ts > strftime('%s', 'now', '-10 days')
      AND s.state NOT IN ('unknown', 'unavailable', '')
),

pv_hourly_states AS (
    /* Fallback, falls noch keine Statistik vorhanden ist */
    SELECT
        date(s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars)) as day_string,
        pvi.id as metadata_id,
        pvi.divisor,
        strftime('%H:00', s.last_updated_ts, 'unixepoch', (SELECT offset FROM vars)) as hour_string,
        MAX(CAST(s.state AS FLOAT)) as max_state_hourly
    FROM states s
    JOIN pv_stat_ids pvi ON s.metadata_id = pvi.states_metadata_id
    WHERE s.last_updated_ts > strftime('%s', 'now', '-10 days')
      AND s.state NOT IN ('unknown', 'unavailable', '')
    GROUP BY 1, 2, 4
),

pv_history_per_sensor AS (
    SELECT
        date(start_ts, 'unixepoch', (SELECT offset FROM vars)) as day_string,
        metadata_id,
        (MAX(CAST(state AS FLOAT)) - MIN(CAST(state AS FLOAT))) / (SELECT divisor FROM pv_stat_ids WHERE id = metadata_id) as single_yield_total,
        (
            MAX(CAST(state AS FLOAT))
            -
            COALESCE(

                MAX(CASE
                    WHEN CAST(strftime('%H', start_ts, 'unixepoch', (SELECT offset FROM vars)) AS INT)
                         < CAST(strftime('%H', 'now', (SELECT offset FROM vars)) AS INT)
                    THEN CAST(state AS FLOAT)
                END),
                MIN(CAST(state AS FLOAT))
            )
        ) / (SELECT divisor FROM pv_stat_ids WHERE id = metadata_id) as single_yield_remaining
    FROM statistics
    WHERE metadata_id IN (SELECT id FROM pv_stat_ids)
      AND start_ts >= (SELECT history_start_ts FROM clock)
    GROUP BY 1, 2

    UNION ALL

    SELECT
        day_string,
        metadata_id,
        (MAX(max_state_hourly) - MIN(max_state_hourly)) / divisor as single_yield_total,

        (
            MAX(max_state_hourly)
            -
            COALESCE(
                MAX(CASE
                    WHEN CAST(SUBSTR(hour_string, 1, 2) AS INT)
                         < CAST(strftime('%H', 'now', (SELECT offset FROM vars)) AS INT)
                    THEN max_state_hourly
                END),
                MIN(max_state_hourly)
            )
        ) / divisor as single_yield_remaining
    FROM pv_hourly_states f
    WHERE NOT EXISTS (
          SELECT 1 FROM statistics st
          WHERE st.metadata_id = f.metadata_id
            AND st.start_ts >= CAST(strftime('%s', f.day_string) AS INTEGER) - (SELECT offset_seconds FROM vars)
            AND st.start_ts < CAST(strftime('%s', f.day_string) AS INTEGER) - (SELECT offset_seconds FROM vars) + 86400
      )
    GROUP BY 1, 2, divisor
),

pv_daily_totals AS (
    SELECT
        day_string,
        ROUND(SUM(COALESCE(single_yield_total, 0.0)), 1) as pv_yield_total,
        ROUND(SUM(COALESCE(single_yield_remaining, 0.0)), 1) as pv_yield_remaining
    FROM pv_history_per_sensor
    GROUP BY 1
),
weather_entity_state_fallback AS (
    SELECT
        CAST(json_extract(a.shared_attrs, '$.cloud_coverage') AS FLOAT) as cloud_val,
        COALESCE(
            CAST(json_extract(a.shared_attrs, '$.uv_index') AS FLOAT),
            CAST(json_extract(a.shared_attrs, '$.uv') AS FLOAT),
            CAST(json_extract(a.shared_attrs, '$.uv_index_value') AS FLOAT)
        ) as uv_val,
        COALESCE(
            CAST(json_extract(a.shared_attrs, '$.temperature') AS FLOAT),
            CAST(json_extract(a.shared_attrs, '$.temp') AS FLOAT),
            CAST(json_extract(a.shared_attrs, '$.temperature_value') AS FLOAT)
        ) as temp_val,
        CASE
            WHEN CAST(json_extract(a.shared_attrs, '$.precipitation_probability') AS FLOAT) IS NOT NULL THEN CAST(json_extract(a.shared_attrs, '$.precipitation_probability') AS FLOAT)
            ELSE
                CASE
                    WHEN COALESCE(
                        CAST(json_extract(a.shared_attrs, '$.precipitation') AS FLOAT),
                        CAST(json_extract(a.shared_attrs, '$.precipitation_rate') AS FLOAT),
                        CAST(json_extract(a.shared_attrs, '$.rain') AS FLOAT)
                    ) IS NULL THEN 0.0
                    WHEN COALESCE(
                        CAST(json_extract(a.shared_attrs, '$.precipitation') AS FLOAT),
                        CAST(json_extract(a.shared_attrs, '$.precipitation_rate') AS FLOAT),
                        CAST(json_extract(a.shared_attrs, '$.rain') AS FLOAT)
                    ) <= 0.05 THEN 0.0
                    WHEN COALESCE(
                        CAST(json_extract(a.shared_attrs, '$.precipitation') AS FLOAT),
                        CAST(json_extract(a.shared_attrs, '$.precipitation_rate') AS FLOAT),
                        CAST(json_extract(a.shared_attrs, '$.rain') AS FLOAT)
                    ) >= 1.05 THEN 100.0
                    ELSE (
                        COALESCE(
                            CAST(json_extract(a.shared_attrs, '$.precipitation') AS FLOAT),
                            CAST(json_extract(a.shared_attrs, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(a.shared_attrs, '$.rain') AS FLOAT)
                        ) - 0.05) * 100.0
                    END
            END as precip_val
    FROM states s
    JOIN state_attributes a ON s.attributes_id = a.attributes_id
    WHERE s.metadata_id = (SELECT w_entity_id FROM ids)
      AND s.last_updated_ts = (
          SELECT MAX(sw.last_updated_ts)
          FROM states sw
          WHERE sw.metadata_id = (SELECT w_entity_id FROM ids)
      )
),
forecast AS (
    SELECT
        -- Today's remaining values (now uses local sun times!)
        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.cloud_coverage') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud_cover') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud_cover_percentage') AS FLOAT),
                CAST(json_extract(f.value, '$.clouds') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud') AS FLOAT)
            ) END), (SELECT cloud_val FROM weather_entity_state_fallback)), 1) as cloud_remaining,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.uv_index') AS FLOAT),
                CAST(json_extract(f.value, '$.uv') AS FLOAT),
                CAST(json_extract(f.value, '$.uv_index_value') AS FLOAT)
            ) END), (SELECT uv_val FROM weather_entity_state_fallback)), 1) as uv_remaining,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.temperature') AS FLOAT),
                CAST(json_extract(f.value, '$.temp') AS FLOAT),
                CAST(json_extract(f.value, '$.temperature_value') AS FLOAT)
            ) END), (SELECT temp_val FROM weather_entity_state_fallback)), 1) as temp_remaining,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN CASE
                WHEN CAST(json_extract(f.value, '$.precipitation_probability') AS FLOAT) IS NOT NULL THEN CAST(json_extract(f.value, '$.precipitation_probability') AS FLOAT)
                ELSE
                    CASE
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) IS NULL THEN 0.0
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) <= 0.05 THEN 0.0
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) >= 1.05 THEN 100.0
                        ELSE (
                            COALESCE(
                                CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                                CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                                CAST(json_extract(f.value, '$.rain') AS FLOAT)
                            ) - 0.05) * 100.0
                        END
                END END), (SELECT precip_val FROM weather_entity_state_fallback)), 1) as precip_remaining,

        -- Values for the following day (now also uses local sun times!)
        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+1 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.cloud_coverage') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud_cover') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud_cover_percentage') AS FLOAT),
                CAST(json_extract(f.value, '$.clouds') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud') AS FLOAT)
            ) END), (SELECT cloud_val FROM weather_entity_state_fallback)), 1) as next_cloud_total,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+1 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.uv_index') AS FLOAT),
                CAST(json_extract(f.value, '$.uv') AS FLOAT),
                CAST(json_extract(f.value, '$.uv_index_value') AS FLOAT)
            ) END), (SELECT uv_val FROM weather_entity_state_fallback)), 1) as next_uv_total,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+1 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.temperature') AS FLOAT),
                CAST(json_extract(f.value, '$.temp') AS FLOAT),
                CAST(json_extract(f.value, '$.temperature_value') AS FLOAT)
            ) END), (SELECT temp_val FROM weather_entity_state_fallback)), 1) as next_temp_total,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+1 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN CASE
                WHEN CAST(json_extract(f.value, '$.precipitation_probability') AS FLOAT) IS NOT NULL THEN CAST(json_extract(f.value, '$.precipitation_probability') AS FLOAT)
                ELSE
                    CASE
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) IS NULL THEN 0.0
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) <= 0.05 THEN 0.0
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) >= 1.05 THEN 100.0
                        ELSE (
                            COALESCE(
                                CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                                CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                                CAST(json_extract(f.value, '$.rain') AS FLOAT)
                            ) - 0.05) * 100.0
                        END
                END END), (SELECT precip_val FROM weather_entity_state_fallback)), 1) as next_precip_total,

        -- Values for the day after tomorrow (used by the 48h hourly forecast sensor)
        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+2 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.cloud_coverage') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud_cover') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud_cover_percentage') AS FLOAT),
                CAST(json_extract(f.value, '$.clouds') AS FLOAT),
                CAST(json_extract(f.value, '$.cloud') AS FLOAT)
            ) END), NULL), 1) as day2_cloud_total,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+2 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.uv_index') AS FLOAT),
                CAST(json_extract(f.value, '$.uv') AS FLOAT),
                CAST(json_extract(f.value, '$.uv_index_value') AS FLOAT)
            ) END), NULL), 1) as day2_uv_total,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+2 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN COALESCE(
                CAST(json_extract(f.value, '$.temperature') AS FLOAT),
                CAST(json_extract(f.value, '$.temp') AS FLOAT),
                CAST(json_extract(f.value, '$.temperature_value') AS FLOAT)
            ) END), NULL), 1) as day2_temp_total,

        ROUND(COALESCE(AVG(CASE
            WHEN substr(json_extract(f.value, '$.datetime'), 1, 10) = date('now', (SELECT offset FROM vars), '+2 day')
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) >= (SELECT sun_start_local FROM pv_activity)
             AND substr(json_extract(f.value, '$.datetime'), 12, 5) <= (SELECT sun_end_local FROM pv_activity)
            THEN CASE
                WHEN CAST(json_extract(f.value, '$.precipitation_probability') AS FLOAT) IS NOT NULL THEN CAST(json_extract(f.value, '$.precipitation_probability') AS FLOAT)
                ELSE
                    CASE
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) IS NULL THEN 0.0
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) <= 0.05 THEN 0.0
                        WHEN COALESCE(
                            CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                            CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                            CAST(json_extract(f.value, '$.rain') AS FLOAT)
                        ) >= 1.05 THEN 100.0
                        ELSE (
                            COALESCE(
                                CAST(json_extract(f.value, '$.precipitation') AS FLOAT),
                                CAST(json_extract(f.value, '$.precipitation_rate') AS FLOAT),
                                CAST(json_extract(f.value, '$.rain') AS FLOAT)
                            ) - 0.05) * 100.0
                        END
                END END), NULL), 1) as day2_precip_total

    FROM states s
    JOIN state_attributes a ON s.attributes_id = a.attributes_id
    CROSS JOIN json_each(a.shared_attrs, '$.forecast') f
    WHERE s.metadata_id = (SELECT forecast_id FROM ids) AND s.last_updated_ts = (SELECT ts FROM latest_forecast_ts)
),

weather_history_hourly AS (
    SELECT
        ts,
        date(ts, 'unixepoch', (SELECT offset FROM vars)) as day_string,
        strftime('%H:%M', ts, 'unixepoch') as hour_string,
        MAX(cloud_val) as cloud_val,
        MAX(uv_val) as uv_val,
        MAX(temp_val) as temp_val,
        COALESCE(MAX(precip_val), 0.0) as precip_val
    FROM weather_history_raw
    GROUP BY ts
),

daily_metrics AS (
    SELECT
        h.day_string,
        ROUND(COALESCE(pvt.pv_yield_total, 0.0), 1) as pv_yield_total,
        ROUND(COALESCE(pvt.pv_yield_remaining, 0.0), 1) as pv_yield_remaining,

        -- REPARATUR: Wenn temp_remaining NULL ist, nimm den Tagesschnitt (temp_total). Ist dieser auch NULL, nimm 15.0
        ROUND(COALESCE(
            AVG(CASE
                WHEN h.hour_string >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
                 AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
                THEN h.temp_val END),
            AVG(CASE
                WHEN h.hour_string >= (SELECT sun_start_local FROM pv_activity)
                 AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
                THEN h.temp_val END),
            15.0
        ), 1) as temp_remaining,

        -- Remaining values for the current day (dynamic from sunrise or current time)
        ROUND(COALESCE(AVG(CASE
            WHEN h.hour_string >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
             AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
            THEN h.cloud_val END), 0.0), 1) as cloud_remaining,

        ROUND(COALESCE(AVG(CASE
            WHEN h.hour_string >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
             AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
            THEN h.uv_val END), 0.0), 1) as uv_remaining,

        ROUND(COALESCE(AVG(CASE
            WHEN h.hour_string >= MAX(strftime('%H:00', 'now', (SELECT offset FROM vars)), (SELECT sun_start_local FROM pv_activity))
             AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
            THEN h.precip_val END), 0.0), 1) as precip_remaining,

        -- Full-day values (strictly between local sunrise and sunset)
        ROUND(COALESCE(AVG(CASE
            WHEN h.hour_string >= (SELECT sun_start_local FROM pv_activity)
             AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
            THEN h.cloud_val END), 0.0), 1) as cloud_total,

        ROUND(COALESCE(AVG(CASE
            WHEN h.hour_string >= (SELECT sun_start_local FROM pv_activity)
             AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
            THEN h.uv_val END), 0.0), 1) as uv_total,

        ROUND(COALESCE(AVG(CASE
            WHEN h.hour_string >= (SELECT sun_start_local FROM pv_activity)
             AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
            THEN h.temp_val END), 15.0), 1) as temp_total,

        ROUND(COALESCE(AVG(CASE
            WHEN h.hour_string >= (SELECT sun_start_local FROM pv_activity)
             AND h.hour_string <= (SELECT sun_end_local FROM pv_activity)
            THEN h.precip_val END), 0.0), 1) as precip_total

    FROM weather_history_hourly h
    LEFT JOIN pv_daily_totals pvt ON h.day_string = pvt.day_string
    WHERE h.day_string != date('now', (SELECT offset FROM vars))
    GROUP BY h.day_string
    HAVING pv_yield_total >= 0.0
       AND COUNT(h.ts) >= 1
       AND AVG(h.cloud_val) IS NOT NULL
),

json_output_assembly AS (
    SELECT json_group_array(
        json_object(
            'day', day_string,
            'remaining', json_object(
                'cloud', cloud_remaining,
                'uv', uv_remaining,
                'temp', temp_remaining,
                'precip', precip_remaining,
                'pv_yield', pv_yield_remaining
            ),
            'total', json_object(
                'cloud', cloud_total,
                'uv', uv_total,
                'temp', temp_total,
                'precip', precip_total,
                'pv_yield', pv_yield_total
            )
        )
    ) as metrics_array
    FROM daily_metrics
)
SELECT json_object(
    'pv_activity', (SELECT json_object('sun_start', sun_start, 'sun_end', sun_end, 'sun_start_local', sun_start_local, 'sun_end_local', sun_end_local) FROM pv_activity),
    'forecast', (SELECT json_object('remaining', json_object('cloud', cloud_remaining, 'uv', uv_remaining, 'temp', temp_remaining, 'precip', precip_remaining), 'next_day_total', json_object('cloud', next_cloud_total, 'uv', next_uv_total, 'temp', next_temp_total, 'precip', next_precip_total), 'day2_total', json_object('cloud', day2_cloud_total, 'uv', day2_uv_total, 'temp', day2_temp_total, 'precip', day2_precip_total)) FROM forecast),
    'live_hour_delta', (SELECT live_hour_delta FROM pv_live_current_hour_delta),
    -- Actual PV yield produced so far today (statistics-based, same source the HA
    -- Energy dashboard uses), lagging up to an hour behind; combined with
    -- live_hour_delta by the today sensor for a near-live total.
    'today_actual', (SELECT ROUND(COALESCE(pv_yield_total, 0.0), 2) FROM pv_daily_totals WHERE day_string = date('now', (SELECT offset FROM vars))),
    'daily_summary', (SELECT metrics_array FROM json_output_assembly)
) as value;"""

DEFAULT_LOVELACE_TEMPLATE_REMAINING_TODAY = DEFAULT_VALUE_TEMPLATE.replace(
    "{{ [final_val, 0.0] | max | round(2) }}",
    """## 📊 PV forecast: **{{ [final_val, 0.0] | max | round(2) }} kWh** remaining today

[More help and setup notes](__HELP_URL__)

{# LOVELACE VARIABLE RE-DECLARATION #}
{% set trend_triggered = namespace(triggered="No (inactive)") %}
{% if global_trend_factor.val < 0.999 %}
  {% set pct = ((1.0 - global_trend_factor.val) * 100) | round(1) %}
  {% set trend_triggered.triggered = "Yes, gradually active (-" ~ pct ~ " %)" %}
{% endif %}

{% set penalty_triggered = namespace(triggered="No") %}
{% if res_val < global_base_yield * global_loo_factor.val * global_trend_factor.val - 0.01 %}
  {% set penalty_triggered.triggered = "Yes (active)" %}
{% endif %}

| Weather parameter | Remaining day (today) |
| :--- | :---:  |
| ☁️ **Cloud cover** | {{ f_avg }} %  |
| ☀️ **UV index** | {{ f_uv_avg }}  |
| 🌡️ **Temperature** | {{ f_temp_avg }} °C |
| 🌧️ **Precipitation** | {{ f_precip_avg }} % |
| 🌧️ **Historical base average** |  {{ base_historical_yield | round(2) }} kWh |
| 🌧️ **Live-smoothed hourly value**  | {{ final_val | round(2) }} kWh |
| 📊 **EMA-smoothed sensor value**  | {{ sensor_value | round(2) if sensor_value is not none else 'N/A' }} kWh |

### ⏳ Top {{display_top_n}} most similar historical comparison days

| Date  | ☁️ Clouds | ☀️ UV | 🌡️ Temp | 🌧️ Rain | Age | Relevance | 🌓 Astro | 🌡️ Temp factor | ⚡ Remaining corr.  |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |  :---: | :---: | :---: |
{% for hist in pool %}{% set p = retune_params if retune_params is mapping else dict() %}{% set t_coef = p.temp_coeff | default(-0.0049) | float %}{% set f_temp_now = fc.remaining.temp | float(default=22.0) %}{% if f_temp_now <= 0.05 %}{% set f_temp_now = f_temp_avg | float(default=22.0) %}{% endif %}{% set hist_day = as_datetime(hist.day).strftime('%j') | int(default=1) %}{% set hist_doy_ang = ((hist_day - 172) * 2 * pi / 365) %}{% set hist_doy_norm = hist_doy_ang - (2 * pi * (hist_doy_ang / (2 * pi)) | int) %}{% set cos_doy_hist = 1.0 - (hist_doy_norm**2 / 2.0) + (hist_doy_norm**4 / 24.0) - (hist_doy_norm**6 / 720.0) %}{% set sun_hist = 0.80 + 0.20 * cos_doy_hist %}{% set dl_hist = 12.0 + 4.0 * (latitude / 50.0) * cos_doy_hist %}{% set cv_list = ns_cv.items | selectattr('day', 'equalto', hist.day) | list %} {{ as_datetime(hist.day).strftime('%d.%m.%Y') }} | {{ hist.cloud }} % | {{ hist.uv | round(1) if hist.uv is defined else '0.0' }} | {{ hist.temp }} °C | {{ hist.precip }} % | {{ hist.days_ago }} d  | **{{ ((hist.w / ([ns_init_def.w, 0.001] | max)) * 100) | round(1) }} %** | x{{ hist.s_korr | round(2) }} | x{{ hist.temp_factor | round(2) }} | **{{ hist.yield | round(2) }} kWh** |
{% endfor %}
<small>Relevance combines clouds, UV, temperature, rain and recency bonus (age) per day. Yields are adjusted by day length (Astro) and temperature.</small>"""
).replace(
    "0.0\n  {% else %}",
    """## 🌙 PV forecast: **0.00 kWh**
***
### 🌙 It is night
* **Status:** No PV generation remaining.
* **Reason:** The current time is after local sunset.
* **Info:** The table for today's remaining yield will be calculated dynamically again tomorrow morning after sunrise.
* **Help:** __HELP_URL__
  {% else %}"""
).replace("__HELP_URL__", HELP_URL)

DEFAULT_LOVELACE_TEMPLATE_TOMORROW = DEFAULT_VALUE_TEMPLATE_TOMORROW.replace(
    "{{ final_capped_val | round(2) }}",
    """## 🔮 PV forecast tomorrow: **{{ final_capped_val | round(2) }} kWh** total yield

[More help and setup notes](__HELP_URL__)


| Weather parameter  | Full day (tomorrow) |
| :--- | :---: |
| ☁️ **Cloud cover**  | {{ f_avg_tomorrow }} % |
| ☀️ **UV index** |  {{ f_uv_avg_tomorrow }} |
| 🌡️ **Temperature**  | {{ f_temp_avg_tomorrow }} °C |
| 🌧️ **Precipitation**  | {{ f_precip_avg_tomorrow }} % |

### ⏳ Top {{display_top_n}} most similar historical comparison days (full day)

| Date | ☁️ Clouds | ☀️ UV | 🌡️ Temp | 🌧️ Rain | Age  | Relevance | 🌓 Astro | 🌡️ Temp factor  | ⚡ Day corr.  |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
{% for hist in pool %}{% set hist_day = as_datetime(hist.day).strftime('%j') | int(default=1) %}{% set hist_doy_ang = ((hist_day - 172) * 2 * pi / 365) %}{% set hist_doy_norm = hist_doy_ang - (2 * pi * (hist_doy_ang / (2 * pi)) | int) %}{% set cos_doy_hist = 1.0 - (hist_doy_norm**2 / 2.0) + (hist_doy_norm**4 / 24.0) - (hist_doy_norm**6 / 720.0) %}{% set sun_hist = 0.80 + 0.20 * cos_doy_hist %}{% set dl_hist = 12.0 + 4.0 * (local_latitude / 50.0) * cos_doy_hist %}| {{ as_datetime(hist.day).strftime('%d.%m.%Y') }} | {{ hist.cloud }} %  | {{ hist.uv | round(1) if hist.uv is defined else '0.0' }} | {{ hist.temp }} °C | {{ hist.precip }} % | {{ hist.days_ago }} d  | **{{ ((hist.w / ([ns_top.total_w, 0.001] | max)) * 100) | round(1) }} %** | x{{ hist.s_korr | round(2) }} | x{{ hist.temp_factor  | round(2) }}  | **{{ hist.yield | round(2) }} kWh** |
{% endfor %}
<small>Relevance combines clouds, UV, temperature, rain and recency bonus (age). Yields are adjusted by day length (Astro) and temperature.</small>"""
).replace("__HELP_URL__", HELP_URL)
