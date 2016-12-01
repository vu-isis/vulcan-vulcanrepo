/*global window */

(function (global) {
    "use strict";

    // Import Globals
    var $ = global.jQuery,
        trace = global.trace,
        $vf = global.$vf;

    // Private variables
    var dropAreaMessage = 'Drag-and-drop hooks here from the list below to install.',
        noAvailableHooksMessage = 'No hooks available.',
        noActiveHooksMessage = 'No active hooks.',
        sortMessage = 'You can drag active hooks to change execution order. Topmost hook is executed first.',

        runHooksOnAllCommitsCaption = 'Run hooks on all commits',
        runHooksOnLastCommitCaption = 'Run hook on last commit',

        confirmTitle = 'Run hooks on all commits?',
        runHooksOnAllCommitsAlert = 'You have chosen to run configured hooks on all commits in repository.'
            + 'that task can take a significant amount of time. ';

    var CommitHookManager = $vf.CommitHookManager = function (config) {

        var that = this,

            availableMessageE,
            availableContainer,
            activeContainer,
            dropAreaE,
            sortMessageE,
            noAvailableHooksMessageE,
            noActiveHooksMessageE,
            runHooksOnAllCommitsE,
            runHooksOnLastCommitE,
            buttonsE,
            confirmE,
            waitContainerE,
            pleaseWaitE,

            activeContainerList,
            availableContainerList;


        // Private methods

        var update = function () {

            if ( that.activeHooks && that.activeHooks.length ) {

                noActiveHooksMessageE.hide();
                activeContainerList.show();

                if ( that.activeHooks.length > 1 ) {

                    sortMessageE.show();
                    activeContainerList.sortable( 'enable' );
                    activeContainerList.sortable( 'refresh' );

                } else {

                    sortMessageE.hide();
                    activeContainerList.sortable( 'disable' );

                }

            } else {

                noActiveHooksMessageE.show();
                activeContainerList.hide();

            }

            if ( that.availableHooks && that.availableHooks.length ) {

                noAvailableHooksMessageE.hide();
                availableContainerList.show();
                dropAreaE.show();

            } else {

                noAvailableHooksMessageE.show();
                availableContainerList.hide();
                dropAreaE.hide();

            }

        };

        var renderBaseHook = function ( data ) {
            return $( '<li/>', {
                'class': 'hook'
            } ).append( $( '<h4/>', {
                'class': 'hook-title',
                'text': data.name
            } ) ).append( $( '<p/>', {
                'class': 'hook-description',
                'text': data.description
            } ) ).data( "hookData", data )
                .disableSelection();
        };

        var removeActive = function ( data ) {

            var hook_id = data.id;

            that.activeHooks = $.grep( that.activeHooks, function ( value ) {
                return value.id != hook_id;
            } );

            that.availableHooks = that.availableHooks || [];
            that.availableHooks.push( data );

            $.ajax( {
                url: that.removeSL.url,
                type: that.removeSL.type,
                data: {
                    hook_id: hook_id,
                    _session_id: $.cookie( '_session_id' )
                },
                dataType: "json",
                success: function () {
                    update();
                },
                error: function () {
                    trace( "Error adding hook" );
                }
            } );
        };

        var renderAvailableHook = function ( data ) {

            var hook = renderBaseHook( data );
            hook.addClass( 'hook-available' )
                .draggable( {
                    revert: true,
                    zIndex: 15000,
                    revertDuration: 250,
                    opacity: 0.7,
                    scroll: true
                } );

            hook.attr( 'title', 'Drag and drop me above to install.' );
            return hook;
        };

        var renderActiveHook = function ( data ) {
            var hook = renderBaseHook( data );

            if ( data.removable === false ) {
                hook.addClass( 'non-removable' );
            } else {
                hook.prepend( $( '<div/>', {
                    'title': 'Deactivate',
                    'class': 'hook-remove',
                    'click': function () {
                        removeActive( data );
                        hook.fadeOut( function () {
                            $( this ).remove();
                        } );
                        availableContainerList.prepend(
                            renderAvailableHook( data )
                        );

                        update();

                        return false;
                    }
                } ) );
            }
            return hook;
        };

        var renderActives = function () {

            $.each( that.activeHooks, function ( i, hookData ) {
                activeContainerList.append( renderActiveHook( hookData ) );
            } );
        };

        var renderAvailables = function () {

            $.each( that.availableHooks, function ( i, hookData ) {
                availableContainerList.append(
                    renderAvailableHook( hookData ) );
            } );
        };

        var loadAvailable = function () {

            pleaseWaitE = new $vf.PleaseWait( 'Loading Hooks', waitContainerE );
            waitContainerE.show();
            pleaseWaitE.show();
            noAvailableHooksMessageE.hide();

            $.ajax( {
                url: that.browsableSL.url,
                type: that.browsableSL.type,
                dataType: "json",
                success: function ( response ) {
                    pleaseWaitE.hide();
                    waitContainerE.hide();
                    that.availableHooks = response.hooks;
                    renderAvailables();
                    update();
                },
                error: function () {
                    trace( "Error loading available hooks" );
                }
            } );
        };

        var addActive = function ( data ) {

            var hook_id = data.id;

            that.availableHooks = $.grep( that.availableHooks, function ( value ) {
                return value.id != hook_id;
            } );

            that.activeHooks = that.activeHooks || [];
            that.activeHooks.push( data );

            $.ajax( {
                url: that.addSL.url,
                type: that.addSL.type,
                data: {
                    hook_id: hook_id,
                    _session_id: $.cookie( '_session_id' )
                },
                dataType: "json",
                success: function () {
                    update();
                },
                error: function () {
                    trace( "Error adding hook" );
                }
            } );
        };

        var setActiveOrder = function () {
            var hook_ids = activeContainerList.find( '.hook' ).map(
                function () {
                    return $( this ).data( 'hookData' ).id;
                } ).get().join( ',' );
            $.ajax( {
                url: that.orderSL.url,
                type: that.orderSL.type,
                data: {
                    hook_ids: hook_ids,
                    _session_id: $.cookie( '_session_id' )
                },
                dataType: "json",
                error: function () {
                    trace( "Error adding hook" );
                }
            } );
        };

        if ( config ) {
            $.extend( that, config );
        }

        // init
        if ( that.containerE !== null ) {
            that.containerE.empty();

            // Display for active items
            activeContainer = $( '<div/>', {
                'class': 'hooks-active-container'
            } ).appendTo( that.containerE );

            activeContainerList = $( '<ul/>', {
                'class': 'deck hooks active'
            } );

            sortMessageE = $( '<p/>', {
                text: sortMessage
            } );

            noActiveHooksMessageE = $( '<p/>', {
                text: noActiveHooksMessage
            } );

            activeContainer.append( $( '<h3/>', {
                text: 'Active Commit Hooks'
            } ) )
                .append( sortMessageE )
                .append( noActiveHooksMessageE );

            activeContainer.append( activeContainerList );

            dropAreaE = $( '<div/>', {
                'class': 'drop-area hook'
            } ).droppable( {
                    accept: '.hook-available',
                    activeClass: 'will-eat',
                    hoverClass: 'drop-area-active',
                    tolerance: 'touch',
                    drop: function ( ev, ui ) {

                        ui.helper.css( 'cursor', ui.helper.data( 'cursorBefore' ) );

                        var el = ui.draggable;
                        var data = el.data( 'hookData' );

                        addActive( data );

                        var hook = renderActiveHook( data ).hide();
                        activeContainerList.append( hook );

                        hook.slideDown();

                        el.remove();

                        update();
                    },
                    over: function ( event, ui ) {
                        ui.helper.data( 'cursorBefore', ui.helper.css( 'cursor' ) );
                        ui.helper.css( 'cursor', 'copy' );
                    },
                    out: function ( event, ui ) {
                        ui.helper.css( 'cursor', ui.helper.data( 'cursorBefore' ) );
                    }

                } );

            dropAreaE.append( $( '<span/>', {
                'class': 'drop-message',
                'text': dropAreaMessage
            } ) );

            activeContainer.append( dropAreaE );

            // Display for available items
            availableContainer = $( '<div/>', {
                'class': 'hooks-available-container'
            } ).appendTo( that.containerE );

            noAvailableHooksMessageE = $( '<p/>', {
                text: noAvailableHooksMessage
            } );

            availableContainer.append( $( '<h3/>', {
                text: 'Installable Commit Hooks'
            } ) )
                .append( noAvailableHooksMessageE );

            availableContainerList = $( '<ul/>', {
                'class': 'deck hooks available'
            } );

            availableMessageE = $( '<div/>', {
                'class': 'availableMessage'
            } );

            availableContainer.append( availableMessageE );

            availableContainer.append( availableContainerList );

            // Waitcontainer
            waitContainerE = $( '<div/>', {
                'class': 'waitContainer'
            } ).hide();
            availableContainer.append( waitContainerE );
            if ( that.activeHooks !== null ) {
                renderActives();
            }


            // render Available hooks
            if ( that.availableHooks !== null ) {
                that.renderAvailables();
            }

            activeContainerList.sortable( {
                update: function () {
                    setActiveOrder();
                },
                distance: 10
            } );

            // Control buttons
            buttonsE = $( '<div/>', {
                'class': 'buttons'
            } );

            this.containerE.append( buttonsE );


            if ( this.runHooksOnAllCommitsSL !== null ) {

                runHooksOnAllCommitsE = $( '<button/>', {
                    title: runHooksOnAllCommitsCaption,
                    text: runHooksOnAllCommitsCaption,
                    'class': 'runHooksOnAllCommits',
                    click: function () {

                        confirmE.dialog( {
                            resizable: false,
                            height: 170,
                            width: 400,
                            modal: true,
                            buttons: {
                                'Go on': function () {
                                    $( this ).dialog( "close" );

                                    $.ajax( {
                                        url: that.runHooksOnAllCommitsSL.url,
                                        type: that.runHooksOnAllCommitsSL.type,
                                        dataType: "json",
                                        data: {
                                            commits: "all",
                                            _session_id: $.cookie('_session_id')
                                        },
                                        success: function (response) {
                                            $('#messages').notify(
                                                response.msg, {status: 'ok'}
                                            );
                                        },
                                        error: function () {
                                            trace( 'Hooks-run failed!' );
                                        }
                                    } );

                                },
                                Cancel: function () {
                                    $( this ).dialog( "close" );
                                }
                            }
                        } );

                    }

                } );

                buttonsE.append( runHooksOnAllCommitsE );
            }

            if ( this.runHooksOnLastCommitSL ) {

                runHooksOnLastCommitE = $('<button/>', {

                    title: runHooksOnLastCommitCaption,
                    text: runHooksOnLastCommitCaption,
                    'class': 'runHooksOnLastCommit',
                    'click': function () {

                        $.ajax( {
                            url: that.runHooksOnLastCommitSL.url,
                            type: that.runHooksOnLastCommitSL.type,
                            dataType: "json",
                            data: {
                                _session_id: $.cookie( '_session_id' )
                            },
                            success: function (response) {
                                $('#messages').notify(
                                    response.msg, {status: 'ok'}
                                );
                            },
                            error: function () {
                                trace( 'Hooks-run failed!' );
                            }
                        } );

                    }

                });

                buttonsE.append( runHooksOnLastCommitE );
            }

            update();
        }


        // Confirm dialog
        confirmE = $( '<div/>', {
            title: confirmTitle,
            html: '<span class="ui-icon ui-icon-alert"></span><span class="confirmMessage">'
                + runHooksOnAllCommitsAlert + '</span>'
        } ).hide();
        $( 'body' ).append( confirmE );


        // Load if needed
        if ( this.autoLoad ) {
            loadAvailable();
        }

        // Public interface
        this.loadAvailable = loadAvailable;

    };

    CommitHookManager.prototype = {
        // data
        activeHooks: null,
        availableHooks: null,

        // service locations
        addSL: null,
        orderSL: null,
        delSL: null,
        browsableSL: null,
        runHooksOnAllCommitsSL: null,
        runHooksOnLastCommitSL: null,

        // DOM Elements
        containerE: null,

        // If it should load stuff automatically

        autoLoad: false

    };


}( window ));