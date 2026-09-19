"""Optional LTA DataMall advisory context.

This package surfaces public passenger-demand and station-crowding context as
read-only, clearly-labelled advisory evidence. It never feeds the solver,
validation, scoring, feasibility or the published CSVs. With no account key it
is inert and makes no outbound request.
"""

from app.modules.datamall.service import DatamallService, get_datamall_service

__all__ = ["DatamallService", "get_datamall_service"]
