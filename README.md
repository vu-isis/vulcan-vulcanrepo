# Vulcan

Vulcan is a framework for enterprise collaboration platforms originally created
for the DARPA Adaptive Vehicle Make (AVM) Program.  There, it provded a foundation
for VehicleFORGE, a platform for cyber-physical system design used to host
AVM's Fast Adaptive Next-Generation (FANG) vehicle design challenges.

VehicleFORGE originated as an early fork of SourceForge's Allura platform, which
is today Apache Allura.  Vulcan was motivated by providing a better organization
as a framework and by adding new forms of extensibility for adapting platform features
and services to an enterprise.

Vulcan is comprised of a core part and a set of optional annexes.
**This repository provides the VulcanRepo annex, which addresses hosted Git and
Subversion version control repositories.**

## Micro-Service Dependencies

Vulcan employs MongoDB for document persistence, Apache Solr for indexing, and Redis
as a key-object store.  In the current release, the following versions of these
dependencies are known to be compatible:

  - MongoDB 3.4.4
  - Apache Solr 6.5.0
  - Redis 3.2.8

Vulcan applications assume these micro-services are deployed in a manner reflecting
the application's requirements.  Deployments of Apache Solr are supported by assets
provided in the *solr\_config* directory.

## Cloud Object Storage

Vulcan employs cloud object storage for artifact persistence, requiring an object
service supporting an AWS S3-compatible API that is accessed via the Python *boto*
package.  This requirement has been satisfied in private cloud deployments using
OpenStack Swift, for example.

## Module Dependencies

Using VulcanRepo with Subversion requires the *pysvn* module.  As the providers
of this module have not seen fit to make it installable using either easy_install
or pip, we cannot include it in normal installation scaffolds like *setup.py* or
a *requirements.txt*.  On Ubuntu, it can be installed using *apt-get* via a
package *python-svn*.


## Repository Hosting

VulcanRepo provides Vulcan applications capabilities for creating, deleting,
authorizing, and browsing hosted Git and Subversion version control system (VCS)
repositories.  It does not provide repository hosting solutions directly, but
merely provides scaffolds that can be used in concert with hosting solutions to
provide proxy authentication and authorization.

Hosting solutions for Git and Subversion are complex subjects, and designers of
Vulcan applications using this annex will need non-casual acquaintance with these
solutions.  Vulcan integrations involving both HTTP and SSH forms of repository
access have been created, but they are typically non-trivial.  With both forms
of access, integration using VulcanRepo implies shared access to the hosted
repositories themselves, which has been addressed by locating the repositories
on Posix-compliant distributed or network file systems.  This solution further
supports horizontal scaling of repository hosting and Vulcan application services.

### HTTP

HTTP forms of proxy authentication and authorization are far easier to pursue,
but not without complexity, particularly with Subversion.  This form of access
has been supported, for example, with hook-based features of the mod_wsgi Apache
module.  VulcanRepo provides web services that can be used in conjunction with
such solutions.  Subversion's added complexity comes from assumptions it makes
about repository layout when served using Apache via the *mod\_dav\_svn* module.
The Vulcan development team can provide more information about solutions to
these challenges.

### SSH

Support for SSH access involves many issues and integration points with the SSH
daemon, with both proxy authentication and access control presenting challenges.
As before, Subversion presents unique challenges.  Vulcan supports associating
public keys with users for key-based SSH authentication.  Features of OpenSSH
(AuthorizedKeysCommand) have been used in concert with web services from
VulcanRepo to leverage this support.  The SSH daemon may use OS services
(getpwnam, etc.) to perform user identification, and solutions such as
NSSCache from Google have been employed.  Within jailed OpenSSH sessions, web
services provided by VulcanRepo can be used for proxy authorization.
Subversion's tunneled svnserve processing in SSH sessions requires more
sophisticated proxy authorization methods, and application designers are again
referred to the Vulcan development team for information about solutions to
these challenges.

## Custom Repository Commit Hooks

Custom repository commit hooks allow Vulcan applications to respond to
repository commits in various ways.  This processing is a pipeline where
application designers can create and register there own agents.  The pipeline
is not exposed to platform users.

To create a custom post-commit hook, simply:

1. Subclass `vulcanrepo.base.model.hook:CommitPlugin` or
`vulcanrepo.base.model.hook:MultiCommitPlugin`. The latter will be called for
every commit, while the former will be called for the latest commit only, when
there are multiple commits submitted to the server more or less simultaneously.

2. Add an entry to `development.ini` for your commit hook, e.g.:

    commit_hook.myhook = path.to.myhook:MyHook

3. Install the commit hook:

    paster sync_commit_hooks

# Release Notes

## Version 2.0.1

Minor Python packaging changes.

## Version 2.0.0

This release is compatible with the Ubuntu Xenial LTS. It is highly recommended
for all application deployments, as it includes critical security fixes to
previous releases.

 - Dates are added to repository browse listings.
 - Repository notifications are improved
 - Added repository-related paster commanda, *clear\_repo\_caches* and *ensure\_repo\_hooks*,
for managing the repository listing caches and ensuring default repository hooks, respectively.
 - Compatibility updates for VulcanForge 2.0.0

